"""One sensor per `update.*` entity, showing its staging status (ready/
waiting/blocked) per semver.py + staging.py, plus the version-jump
classification and (while waiting) how much longer, as attributes.

Deliberately minimal so far: auto-discovers update entities at startup and
whenever a new one appears. No auto-install/rollout-pacing/install-log yet.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import EventStateChangedData, async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .semver import classify_version_jump
from .staging import evaluate_staging

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

# Same lookback window previous-state-tracker's config_flow.py already uses
# for its own best-effort recorder history lookup.
_HISTORY_LOOKBACK = timedelta(days=30)


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
        async_add_entities([UpdateStagingSensor(entity_id) for entity_id in new_ids])

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


async def _async_available_since(hass: HomeAssistant, entity_id: str, current_latest_version: str) -> datetime:
    """Best-effort: when did `latest_version` first become its current
    value? Falls back to "now" (the conservative choice -- treats it as
    brand new, so any wait period starts from scratch) whenever recorder
    history can't answer that, e.g. recorder not loaded, this entity
    excluded from recording, or genuinely no history yet."""
    now = dt_util.utcnow()
    try:
        from homeassistant.components.recorder import get_instance, history, is_entity_recorded

        if not is_entity_recorded(hass, entity_id):
            return now

        start = now - _HISTORY_LOOKBACK
        result = await get_instance(hass).async_add_executor_job(
            history.get_significant_states,
            hass,
            start,
            now,
            [entity_id],
            None,  # filters
            False,  # include_start_time_state
            False,  # significant_changes_only -- want every value seen, not just the "big" ones
            False,  # minimal_response
            False,  # no_attributes -- need latest_version, unlike previous-state-tracker's lookup
        )
        states = result.get(entity_id, [])

        available_since = now
        matched_to_window_start = True
        for state in reversed(states):
            if state.attributes.get("latest_version") == current_latest_version:
                available_since = state.last_changed
            else:
                matched_to_window_start = False
                break

        if states and matched_to_window_start:
            # Matched every record we have, all the way back to the start
            # of the lookback window -- it's been this value at least that
            # long, quite possibly longer; `start` is the best lower bound
            # available, not a claim that it appeared exactly then.
            return start
        return available_since
    except Exception:
        _LOGGER.debug("Couldn't look up update history for %s", entity_id, exc_info=True)
        return now


class UpdateStagingSensor(SensorEntity, RestoreEntity):
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, tracked_entity_id: str) -> None:
        self._tracked_entity_id = tracked_entity_id
        self._attr_unique_id = f"{DOMAIN}_{tracked_entity_id}_staging"
        self._attr_name = f"{tracked_entity_id} staging"
        self._attr_native_value: str | None = None
        self._attr_extra_state_attributes: dict[str, str | int | None] = {
            "tracked_entity_id": tracked_entity_id,
            "version_jump": None,
            "remaining_seconds": None,
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()
        if last_state:
            self._attr_native_value = last_state.state
            if "version_jump" in last_state.attributes:
                self._attr_extra_state_attributes["version_jump"] = last_state.attributes["version_jump"]

        await self._async_update_state(self.hass.states.get(self._tracked_entity_id))
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._tracked_entity_id], self._handle_state_change
            )
        )

    @callback
    def _handle_state_change(self, event: Event[EventStateChangedData]) -> None:
        self.hass.async_create_task(self._async_update_state(event.data.get("new_state")))

    async def _async_update_state(self, state: State | None) -> None:
        if state is None:
            self._attr_native_value = None
            self._attr_extra_state_attributes["version_jump"] = None
            self._attr_extra_state_attributes["remaining_seconds"] = None
            if self.hass.is_running:
                self.async_write_ha_state()
            return

        current = state.attributes.get("installed_version")
        latest = state.attributes.get("latest_version")
        if not current or not latest:
            self._attr_native_value = None
            self._attr_extra_state_attributes["version_jump"] = None
            self._attr_extra_state_attributes["remaining_seconds"] = None
            if self.hass.is_running:
                self.async_write_ha_state()
            return

        jump = classify_version_jump(current, latest)
        available_since = await _async_available_since(self.hass, self._tracked_entity_id, latest)
        result = evaluate_staging(jump, available_since, dt_util.utcnow())

        self._attr_native_value = result.status
        self._attr_extra_state_attributes["version_jump"] = jump
        self._attr_extra_state_attributes["remaining_seconds"] = (
            round(result.remaining.total_seconds()) if result.remaining is not None else None
        )
        if self.hass.is_running:
            self.async_write_ha_state()
