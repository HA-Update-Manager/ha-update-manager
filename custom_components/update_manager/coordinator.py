"""Owns the one shared computation of "how should each pending update be
staged right now". Built once per config entry and read by both the summary
sensor (a cheap debug view, see FUTURE.md) and, eventually, the websocket API
Phase 2's panel will use -- neither should duplicate this refresh logic or
the recorder lookups it can trigger.

Also the single place that notices when an update actually completes
(installed_version changed), regardless of who/what triggered it, and tells
anyone who registered an install listener (see install_log.py) -- Update
Manager doesn't call `update.install` itself yet, so this is the only way to
learn an install happened at all.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers.event import EventStateChangedData
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
)
from .semver import classify_version_jump
from .staging import DEFAULT_RULES, StagingRules, evaluate_staging

_LOGGER = logging.getLogger(__name__)

# Same lookback window previous-state-tracker's config_flow.py already uses
# for its own best-effort recorder history lookup.
_HISTORY_LOOKBACK = timedelta(days=30)

# Brief pause between recorder history lookups during the initial bulk
# scan at startup -- a large instance can have 100+ update entities, and
# firing that many recorder queries back to back right at startup (already
# a busy time) isn't necessary just because we technically can.
_STARTUP_QUERY_STAGGER = 0.05

InstallListener = Callable[[str, str, str, State], None]


def rules_from_options(options: dict) -> StagingRules:
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


class UpdateManagerCoordinator:
    def __init__(self, hass: HomeAssistant, rules: StagingRules) -> None:
        self.hass = hass
        self.rules = rules
        # entity_id -> {"entity_id", "version_jump", "status", "remaining_seconds", "installable"}
        self.cache: dict[str, dict] = {}
        self._listeners: list[Callable[[], None]] = []
        self._install_listeners: list[InstallListener] = []
        self._unsub_state_changed: Callable[[], None] | None = None

    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Registers a callback fired after any recompute. Returns an unsub."""
        self._listeners.append(listener)

        def _remove() -> None:
            self._listeners.remove(listener)

        return _remove

    def async_add_install_listener(self, listener: InstallListener) -> Callable[[], None]:
        """Registers a callback fired whenever an update entity's
        installed_version actually changes (an install completed, by
        whatever means)."""
        self._install_listeners.append(listener)

        def _remove() -> None:
            self._install_listeners.remove(listener)

        return _remove

    async def async_start(self) -> None:
        for entity_id in self.hass.states.async_entity_ids("update"):
            await self._async_refresh_one(entity_id)
            await asyncio.sleep(_STARTUP_QUERY_STAGGER)

        self._unsub_state_changed = self.hass.bus.async_listen(
            "state_changed", self._handle_state_changed, run_immediately=True
        )

    @callback
    def async_stop(self) -> None:
        if self._unsub_state_changed is not None:
            self._unsub_state_changed()
            self._unsub_state_changed = None

    @callback
    def _handle_state_changed(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        if not entity_id.startswith("update."):
            return

        old_state = event.data["old_state"]
        new_state = event.data["new_state"]

        old_installed = old_state.attributes.get("installed_version") if old_state else None
        new_installed = new_state.attributes.get("installed_version") if new_state else None
        if old_installed is not None and new_installed is not None and old_installed != new_installed:
            for listener in list(self._install_listeners):
                listener(entity_id, old_installed, new_installed, new_state)

        old_latest = old_state.attributes.get("latest_version") if old_state else None
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
        for listener in list(self._listeners):
            listener()

    async def _async_refresh_one(self, entity_id: str) -> None:
        state = self.hass.states.get(entity_id)
        if state is None:
            self.cache.pop(entity_id, None)
            return

        # HA's own update entities are always exactly "on" (an update is
        # available) or "off" (already up to date) -- that's the correct,
        # authoritative check for "is there anything to report here at
        # all", not comparing installed_version/latest_version ourselves.
        if state.state != "on":
            self.cache.pop(entity_id, None)
            return

        current = state.attributes.get("installed_version")
        latest = state.attributes.get("latest_version")
        if not current or not latest:
            self.cache.pop(entity_id, None)
            return

        jump = classify_version_jump(current, latest)
        now = dt_util.utcnow()
        # Uses this entry's actual configured rules (options flow), not
        # always the hardcoded defaults -- a user may have given major/
        # unknown a real wait instead of "always blocked" (see FUTURE.md).
        # Only skip the recorder query when the *configured* wait for this
        # jump is None, since only then can available_since not change the
        # answer.
        rules = self.rules
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
        self.cache[entity_id] = {
            "entity_id": entity_id,
            "version_jump": jump,
            "status": result.status,
            "remaining_seconds": (
                round(result.remaining.total_seconds()) if result.remaining is not None else None
            ),
            "installable": installable,
            # Exposed mainly so the recorder lookup above can actually be
            # checked by hand (diagnostics download) instead of only being
            # inferable from status/remaining_seconds.
            "available_since": available_since.isoformat(),
        }
