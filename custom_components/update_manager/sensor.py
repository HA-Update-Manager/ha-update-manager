"""A single "Update Manager" summary sensor, not one entity per `update.*`
entity -- a large instance can easily have 100+ update entities, which
would otherwise mean 100+ near-useless extra entities, pure clutter for
what's fundamentally one overview. State is the number of updates ready to
install now; the per-update breakdown (version jump, status, remaining
wait) lives in this one entity's attributes instead, the same data Phase
2's panel would eventually read to build its table.

Deliberately minimal so far: read-only, no auto-install/rollout-pacing
wired up yet.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import EventStateChangedData
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

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
)
from .semver import classify_version_jump
from .staging import DEFAULT_RULES, StagingRules, evaluate_staging


def _rules_from_options(options: dict) -> StagingRules:
    """Builds a StagingRules from the options flow's stored values, falling
    back to staging.DEFAULT_RULES for anything not set yet (e.g. before the
    options flow has ever been completed)."""

    def _wait(days_key: str, blocked_key: str, default: timedelta | None) -> timedelta | None:
        if blocked_key not in options and days_key not in options:
            return default
        if options.get(blocked_key, False):
            return None
        return timedelta(days=options.get(days_key, 0))

    return StagingRules(
        patch_wait=_wait(CONF_PATCH_WAIT_DAYS, CONF_PATCH_BLOCKED, DEFAULT_RULES.patch_wait),
        minor_wait=_wait(CONF_MINOR_WAIT_DAYS, CONF_MINOR_BLOCKED, DEFAULT_RULES.minor_wait),
        major_wait=_wait(CONF_MAJOR_WAIT_DAYS, CONF_MAJOR_BLOCKED, DEFAULT_RULES.major_wait),
        unknown_wait=_wait(CONF_UNKNOWN_WAIT_DAYS, CONF_UNKNOWN_BLOCKED, DEFAULT_RULES.unknown_wait),
    )

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

# Same lookback window previous-state-tracker's config_flow.py already uses
# for its own best-effort recorder history lookup.
_HISTORY_LOOKBACK = timedelta(days=30)

# Brief pause between recorder history lookups during the initial bulk
# scan at startup -- a large instance can have 100+ update entities, and
# firing that many recorder queries back to back right at startup (already
# a busy time) isn't necessary just because we technically can.
_STARTUP_QUERY_STAGGER = 0.05


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    rules = _rules_from_options(dict(config_entry.options))
    async_add_entities([UpdateManagerSummarySensor(rules)])


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


class UpdateManagerSummarySensor(SensorEntity, RestoreEntity):
    _attr_should_poll = False
    _attr_unique_id = f"{DOMAIN}_summary"
    _attr_name = "Update Manager"
    _attr_icon = "mdi:update"

    def __init__(self, rules: StagingRules) -> None:
        self._rules = rules
        # entity_id -> {"entity_id", "version_jump", "status", "remaining_seconds"}
        self._cache: dict[str, dict] = {}
        self._attr_native_value: int | None = None
        self._attr_extra_state_attributes: dict = {
            "updates": [],
            "ready_count": 0,
            "waiting_count": 0,
            "blocked_count": 0,
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()
        if last_state:
            try:
                self._attr_native_value = int(last_state.state)
            except (TypeError, ValueError):
                pass

        for entity_id in self.hass.states.async_entity_ids("update"):
            await self._async_refresh_one(entity_id)
            await asyncio.sleep(_STARTUP_QUERY_STAGGER)
        self._recompute_aggregate()

        self.async_on_remove(
            self.hass.bus.async_listen("state_changed", self._handle_state_changed, run_immediately=True)
        )

    @callback
    def _handle_state_changed(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        if not entity_id.startswith("update."):
            return

        old_state = event.data["old_state"]
        new_state = event.data["new_state"]
        old_installed = old_state.attributes.get("installed_version") if old_state else None
        old_latest = old_state.attributes.get("latest_version") if old_state else None
        new_installed = new_state.attributes.get("installed_version") if new_state else None
        new_latest = new_state.attributes.get("latest_version") if new_state else None
        old_key = (old_state.state, old_installed, old_latest) if old_state else None
        new_key = (new_state.state, new_installed, new_latest) if new_state else None
        if old_state is not None and new_state is not None and old_key == new_key:
            # Some other attribute changed (e.g. in_progress toggling
            # during an install) -- not something a fresh recorder lookup
            # would answer differently, skip it rather than re-querying.
            return

        self.hass.async_create_task(self._async_handle_changed(entity_id))

    async def _async_handle_changed(self, entity_id: str) -> None:
        await self._async_refresh_one(entity_id)
        self._recompute_aggregate()
        if self.hass.is_running:
            self.async_write_ha_state()

    async def _async_refresh_one(self, entity_id: str) -> None:
        state = self.hass.states.get(entity_id)
        if state is None:
            self._cache.pop(entity_id, None)
            return

        # HA's own update entities are always exactly "on" (an update is
        # available) or "off" (already up to date) -- that's the correct,
        # authoritative check for "is there anything to report here at
        # all", not comparing installed_version/latest_version ourselves.
        # Skipping this meant every already-up-to-date entity (the normal,
        # steady-state case for almost all of them) got its versions
        # compared as equal, classified "unknown", and counted as
        # "blocked" -- on a real instance, that's most or all entities,
        # not a handful of genuine edge cases.
        if state.state != "on":
            self._cache.pop(entity_id, None)
            return

        current = state.attributes.get("installed_version")
        latest = state.attributes.get("latest_version")
        if not current or not latest:
            self._cache.pop(entity_id, None)
            return

        jump = classify_version_jump(current, latest)
        now = dt_util.utcnow()
        # Uses this entry's actual configured rules (options flow), not
        # always the hardcoded defaults -- a user may have given major/
        # unknown a real wait instead of "always blocked" (see FUTURE.md).
        # Only skip the recorder query when the *configured* wait for this
        # jump is None, since only then can available_since not change the
        # answer.
        rules = self._rules
        configured_wait = {
            "patch": rules.patch_wait,
            "minor": rules.minor_wait,
            "major": rules.major_wait,
            "unknown": rules.unknown_wait,
        }[jump]
        if configured_wait is None:
            available_since = now
        else:
            available_since = await _async_available_since(self.hass, entity_id, latest)
        result = evaluate_staging(jump, available_since, now, rules)
        # UpdateEntityFeature.INSTALL = 1 (homeassistant/components/update/const.py):
        # some update entities (e.g. firmware that must be flashed manually)
        # only ever report that a newer version exists, with no install
        # action at all -- ready/waiting/blocked is still meaningful for
        # "should you move to this version", but this must gate any future
        # auto-install: never call update.install on an entity that doesn't
        # support it.
        installable = bool(state.attributes.get("supported_features", 0) & 1)
        self._cache[entity_id] = {
            "entity_id": entity_id,
            "version_jump": jump,
            "status": result.status,
            "remaining_seconds": (
                round(result.remaining.total_seconds()) if result.remaining is not None else None
            ),
            "installable": installable,
        }

    def _recompute_aggregate(self) -> None:
        updates = list(self._cache.values())
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
