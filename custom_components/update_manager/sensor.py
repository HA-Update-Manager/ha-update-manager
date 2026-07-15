"""Classifies every existing `update.*` entity's pending version jump
(patch/minor/major/unknown) using semver.classify_version_jump.

Deliberately minimal for now: auto-discovers update entities at startup and
whenever a new one appears, one sensor per update entity. No staging/
wait-time/auto-install behavior yet -- this only shows the classification,
so there's something real to see in a running instance before that logic
exists.
"""
from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import EventStateChangedData, async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .semver import classify_version_jump

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    known: set[str] = set()

    @callback
    def _add_new(entity_ids: set[str]) -> None:
        new_ids = entity_ids - known
        if not new_ids:
            return
        known.update(new_ids)
        async_add_entities([VersionJumpSensor(entity_id) for entity_id in new_ids])

    _add_new(set(hass.states.async_entity_ids("update")))

    @callback
    def _state_changed(event: Event[EventStateChangedData]) -> None:
        # A newly-appearing update entity is exactly "no old_state, has a
        # new_state" -- cheaper than re-scanning all entity_ids on every
        # unrelated state change, and doesn't depend on entity-registry
        # timing (some update entities may never be registered there).
        if event.data["old_state"] is None and event.data["new_state"] is not None:
            _add_new({event.data["new_state"].entity_id})

    config_entry.async_on_unload(
        hass.bus.async_listen("state_changed", _state_changed, run_immediately=True)
    )


class VersionJumpSensor(SensorEntity, RestoreEntity):
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, tracked_entity_id: str) -> None:
        self._tracked_entity_id = tracked_entity_id
        self._attr_unique_id = f"{DOMAIN}_{tracked_entity_id}_version_jump"
        self._attr_name = f"{tracked_entity_id} version jump"
        self._attr_native_value: str | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()
        if last_state:
            self._attr_native_value = last_state.state

        self._update_state(self.hass.states.get(self._tracked_entity_id))
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._tracked_entity_id], self._handle_state_change
            )
        )

    @callback
    def _handle_state_change(self, event: Event[EventStateChangedData]) -> None:
        self._update_state(event.data.get("new_state"))
        if self.hass.is_running:
            self.async_write_ha_state()

    def _update_state(self, state: State | None) -> None:
        if state is None:
            self._attr_native_value = None
            return
        current = state.attributes.get("installed_version")
        latest = state.attributes.get("latest_version")
        if not current or not latest:
            self._attr_native_value = None
            return
        self._attr_native_value = classify_version_jump(current, latest)
