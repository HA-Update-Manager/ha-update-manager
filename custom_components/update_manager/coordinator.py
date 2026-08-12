"""Owns the one shared computation of "how should each pending update be
staged right now". Built once per config entry and read by both the summary
sensor (a cheap debug view) and the panel's own websocket API -- neither
should duplicate this refresh logic or the recorder lookups it can trigger.

Also the single place that notices when an update actually completes
(installed_version changed), regardless of who/what triggered it (a manual
click, or install_manager.py's own auto-install), and tells anyone who
registered an install listener (see install_log.py).
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.update import UpdateEntityFeature
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import EventStateChangedData, async_track_point_in_time, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .community_verdict import CommunityVerdictManager
from .const import (
    CONF_EXCLUDED_ENTITIES,
    CONF_LARGE_WAIT_DAYS,
    CONF_MEDIUM_WAIT_DAYS,
    CONF_SMALL_WAIT_DAYS,
    CONF_TRUSTED_VOTERS,
    DEFAULT_WAIT_DAYS,
    DOMAIN,
    WEEKDAY_READY_OPTION_KEYS,
)
from .hacs_identity import corrected_release_url
from .postponement_schedule import DayRule, EMPTY_SCHEDULE, PostponementSchedule, next_allowed_ready
from .semver import classify_version_size
from .staging import StagingRules, StagingResult, evaluate_staging, wait_for_size

_LOGGER = logging.getLogger(__name__)

_AVAILABLE_SINCE_STORAGE_VERSION = 1
_AVAILABLE_SINCE_STORAGE_KEY = f"{DOMAIN}_available_since"

_LAST_INSTALLED_STORAGE_VERSION = 1
_LAST_INSTALLED_STORAGE_KEY = f"{DOMAIN}_last_installed_version"

_FORCE_READY_STORAGE_VERSION = 1
_FORCE_READY_STORAGE_KEY = f"{DOMAIN}_force_ready"

# Several Zigbee2MQTT-backed update entities briefly report this literal
# string as their own installed_version right after a restart, before the
# device's real firmware version has synced back over MQTT -- confirmed
# live, 2026-08-09, via diagnostics showing install_log entries with
# "from_version": "-1". Excluded everywhere installed_version feeds this
# module's own restart-recovery baseline (both the write side and the
# comparison side, see each call site's own comment), a shared constant
# rather than the same literal repeated at both -- found by code review,
# 2026-08-10.
_PLACEHOLDER_INSTALLED_VERSION = "-1"

# Same lookback window previous-state-tracker's config_flow.py already uses
# for its own best-effort recorder history lookup.
_HISTORY_LOOKBACK = timedelta(days=30)

# How long a pending entity can sit genuinely unavailable before
# _async_refresh_one evicts it from self.cache outright, rather than on the
# very first unavailable state_changed event -- same phenomenon, same 2
# minutes, as rollout_manager.py's own _UNAVAILABLE_GRACE (a Zigbee device
# going briefly unavailable mid-OTA, an MQTT reconnect blip, is common and
# usually resolves itself). Found live, 2026-08-10: a genuinely still-
# installing entity briefly reporting unavailable got dropped from
# self.cache entirely on the spot, disappearing from update_manager/updates'
# own response -- and so from the panel's Installing section -- until some
# unrelated later trigger happened to reload it. The panel's own
# _checkForNewUpdateEntities only ever re-discovers an entity_id it hasn't
# seen *available* before; an already-known one vanishing from this.cache
# and reappearing doesn't trip that check at all, so nothing client-side
# was going to recover this on its own.
_CACHE_UNAVAILABLE_GRACE = timedelta(minutes=2)

# Home Assistant Core/Supervisor/OS's own update entities, identified by
# their unique_id (verified against homeassistant/components/hassio/
# entity.py's HassioCoreEntity/HassioSupervisorEntity/HassioOSEntity --
# f"home_assistant_{core,supervisor,os}_{ATTR_VERSION_LATEST}", and
# ATTR_VERSION_LATEST = "version_latest" per hassio/const.py). Matched by
# unique_id rather than by platform == "hassio": that platform also
# provides regular add-ons' update entities, which are a different,
# per-entity configurable category, not this one. Also which
# specific one (core/supervisor/os), for callers that need to tell them
# apart, not just identify all three (see home_assistant_component_for_entity
# below, shared with install_tiers.py's own tier_for_entity).
_HOME_ASSISTANT_COMPONENT_BY_UNIQUE_ID = {
    "home_assistant_core_version_latest": "core",
    "home_assistant_supervisor_version_latest": "supervisor",
    "home_assistant_os_version_latest": "os",
}

# A registry entry's unique_id is whatever it was when first created, not
# whatever today's hassio/entity.py would generate -- it doesn't get
# migrated just because the integration's own code changed since. Found
# live: a real instance's Core/Supervisor/OS update entities didn't match
# _HOME_ASSISTANT_COMPONENT_BY_UNIQUE_ID at all, despite that matching
# current source. These conventional entity_ids are the fallback for
# exactly that drift -- not the primary check (entity_id can, in the
# abstract, be renamed, unique_id can't), but nobody actually renames
# these three in practice, so it's a safe net for whatever unique_id
# scheme a given instance's registry happens to still be carrying.
_HOME_ASSISTANT_COMPONENT_BY_ENTITY_ID = {
    "update.home_assistant_core_update": "core",
    "update.home_assistant_supervisor_update": "supervisor",
    "update.home_assistant_operating_system_update": "os",
}


def home_assistant_component_for_entity(
    hass: HomeAssistant, entity_id: str, *, entry: er.RegistryEntry | None = None
) -> str | None:
    """"core"/"supervisor"/"os" if entity_id is one of Home Assistant's own
    three update entities (unique_id-first, entity_id-fallback, see
    _HOME_ASSISTANT_COMPONENT_BY_ENTITY_ID's own drift comment above), else
    None. Shared with install_tiers.py's own tier_for_entity, which needs
    this same identification for its own, unrelated reason (the tier gate)
    -- found by review: that module had grown its own second, weaker copy
    (entity_id only, no unique_id fallback) of these three entities.

    entry: pass an already-fetched registry entry when the caller needs one
    for its own further checks too (tier_for_entity's own translation_key
    check right after this) -- avoids a second, redundant entity-registry
    lookup for the same entity_id, found by code review, 2026-08-10.
    Fetched fresh here when omitted."""
    if entry is None:
        entry = er.async_get(hass).async_get(entity_id)
    if entry is not None and entry.unique_id in _HOME_ASSISTANT_COMPONENT_BY_UNIQUE_ID:
        return _HOME_ASSISTANT_COMPONENT_BY_UNIQUE_ID[entry.unique_id]
    return _HOME_ASSISTANT_COMPONENT_BY_ENTITY_ID.get(entity_id)


def _is_excluded_from_auto_install(entity_id: str, excluded_entities: frozenset[str]) -> bool:
    """Whatever the user picked on the settings screen (Core/Supervisor/OS
    included -- they're pre-populated default members of this same list,
    see __init__.py's own _migrate_default_excluded_entities, not a second,
    separate hard-coded exclusion anymore). Still shown normally in
    Updates/History either way, install_manager.py just never
    auto-installs it."""
    return entity_id in excluded_entities


# The shape any status without a countdown attached to it uses, whether
# that's staging.py's own "blocked"/a "ready" that isn't projected any
# further out, or coordinator.py's own "skipped" (which isn't a StagingResult
# at all, see status_now's own comment) -- one literal, reused everywhere
# this shape is needed instead of each call site hand-writing its own copy.
_NO_TIMING_FIELDS = {"remaining_seconds": None, "ready_at": None}


def _cache_timing_fields(result: StagingResult, now: datetime) -> dict:
    """remaining_seconds and ready_at together, from the same StagingResult
    and the same `now` -- shared by every caller that derives them
    (_derive_status_fields, and _cache_skipped's own None/None shape) so the
    two can't drift apart from each other. ready_at is an absolute instant,
    not something a reader has to reconstruct by re-adding remaining_seconds
    to whatever `now` happens to be by the time they read it. remaining_seconds
    is kept alongside it, still needed for the panel's own sort order
    (soonest-first) without re-deriving a duration from ready_at every time.

    Storing either of these anywhere and trusting that storage to still be
    accurate later is the actual mistake to avoid -- see
    _derive_status_fields's own docstring for the two earlier attempts (a
    plain periodic recompute, then a precise per-entity wakeup timer on top
    of it) that each only shrank that staleness window instead of
    eliminating it. status_now calls this fresh at the exact instant it's
    actually needed instead."""
    if result.remaining is None:
        return dict(_NO_TIMING_FIELDS)
    return {
        "remaining_seconds": round(result.remaining.total_seconds()),
        "ready_at": (now + result.remaining).isoformat(),
    }


def excluded_entities_from_options(options: dict) -> frozenset[str]:
    return frozenset(options.get(CONF_EXCLUDED_ENTITIES, []))


def trusted_voters_from_options(options: dict) -> list[str]:
    return list(options.get(CONF_TRUSTED_VOTERS, []))

# Brief pause between recorder history lookups during the initial bulk
# scan at startup -- a large instance can have 100+ update entities, and
# firing that many recorder queries back to back right at startup (already
# a busy time) isn't necessary just because we technically can.
_STARTUP_QUERY_STAGGER = 0.05

# state_changed only fires again once an entity's own state/installed_version/
# latest_version actually changes -- a wait period can elapse with no such
# change at all (the entity just sits there reporting the same pending
# update), and without a separate timer nothing would ever recompute
# status/remaining_seconds for it again. Found live: an update stuck on
# "waiting" whose entity never changed state afterward stayed "waiting"
# forever and was never announced/auto-installed, even once its configured
# wait had long since elapsed. Purely a recompute from already-cached facts
# (no recorder round-trip, see async_update_rules's own comment) so a
# frequent-ish interval is cheap; 15 minutes is well under the coarsest
# configurable wait granularity (whole days) so it doesn't visibly lag.
_RECHECK_INTERVAL = timedelta(minutes=15)

InstallListener = Callable[[str, str, str, State], None]


def rules_from_options(options: dict) -> StagingRules:
    """Builds a StagingRules from the settings panel's stored values, falling
    back to const.py's own DEFAULT_WAIT_DAYS for anything not set yet (e.g.
    before the settings have ever been saved) -- not staging.py's own
    DEFAULT_RULES, whose large_wait=None means "always blocked". DEFAULT_WAIT_DAYS
    gives "large" a real, finite wait, so a freshly-created config entry
    (options == {}) reads like a freshly-saved default setup, not like a
    deliberate "block all major updates forever" choice nobody actually
    made. Fixed 2026-07-16: found live -- a brand new install showed a major
    update as blocked/red before anyone had ever opened the settings tab."""

    def _wait(days_key: str) -> timedelta:
        return timedelta(days=options.get(days_key, DEFAULT_WAIT_DAYS[days_key]))

    return StagingRules(
        small_wait=_wait(CONF_SMALL_WAIT_DAYS),
        medium_wait=_wait(CONF_MEDIUM_WAIT_DAYS),
        large_wait=_wait(CONF_LARGE_WAIT_DAYS),
    )


def schedule_from_options(options: dict) -> PostponementSchedule:
    """Builds a PostponementSchedule from the settings panel's stored values
    -- WEEKDAY_READY_OPTION_KEYS is already in PostponementSchedule.days'
    own Monday..Sunday order, so this is a straight zip, no per-day branching
    needed. Every day defaults to disabled/no-time when its own keys are
    absent (a freshly-created config entry, or an existing one that's never
    touched this setting), giving EMPTY_SCHEDULE-equivalent behavior with no
    migration required -- see const.py's own WEEKDAY_READY_OPTION_KEYS
    comment."""

    def _day(enabled_key: str, time_key: str) -> DayRule:
        raw_time = options.get(time_key) or None
        return DayRule(
            enabled=bool(options.get(enabled_key, False)),
            time=dt_util.parse_time(raw_time) if raw_time else None,
        )

    return PostponementSchedule(
        days=tuple(_day(enabled_key, time_key) for enabled_key, time_key in WEEKDAY_READY_OPTION_KEYS)
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
    def __init__(
        self,
        hass: HomeAssistant,
        rules: StagingRules,
        excluded_entities: frozenset[str] = frozenset(),
        community_verdict_manager: CommunityVerdictManager | None = None,
        schedule: PostponementSchedule = EMPTY_SCHEDULE,
    ) -> None:
        self.hass = hass
        self.rules = rules
        self.excluded_entities = excluded_entities
        self.schedule = schedule
        # Cached alongside self.schedule itself (see async_update_rules'
        # own matching assignment below), not rescanned inside
        # _apply_schedule_gate on every single cached entity, every
        # periodic recheck and every per-entity refresh -- the default,
        # untouched-by-any-install state is every day disabled, so most
        # installs would otherwise pay a 7-day scan (and a timezone
        # conversion, see _apply_schedule_gate's own comment) per entity for
        # a result that's always thrown away.
        self._schedule_active = any(day.enabled for day in schedule.days)
        # None-able (unlike every other manager reference this coordinator
        # holds) so this class still works standalone without it, e.g. in a
        # future test, see community_verdict.py's own docstring for what
        # this is for, purely read-only, no effect on staging status itself.
        self._community_verdict_manager = community_verdict_manager
        # entity_id -> {"entity_id", "version_size", "status", "remaining_seconds", "ready_at", "installable"}
        self.cache: dict[str, dict] = {}
        # entity_id -> {"version", "since"}: the authoritative "when did
        # `version` first become this entity's latest_version" record, see
        # _async_get_available_since. Persisted (unlike self.cache, which is
        # rebuilt from scratch on every restart) precisely because it must
        # survive a restart intact: direct user feedback, the recorder-only
        # lookup this replaces could quietly reset an update's wait back to
        # "just now" after a restart, the entity briefly going unavailable,
        # or an integration reload, none of which mean the update actually
        # just became available again.
        self._available_since: dict[str, dict[str, str]] = {}
        self._available_since_store: Store[dict[str, dict[str, str]]] = Store(
            hass, _AVAILABLE_SINCE_STORAGE_VERSION, _AVAILABLE_SINCE_STORAGE_KEY
        )
        # entity_id -> this entity's own installed_version, as of the last
        # time we saw it (any refresh, not just an install) -- persisted
        # (unlike self.cache) precisely so a restart has something to
        # compare the live post-restart value against, see
        # _async_recover_install_across_restart. Installing HA Core itself
        # (and likely Supervisor/OS) always requires a full HA restart, so
        # the before/after installed_version transition happens *across*
        # that restart boundary -- _handle_state_changed only ever compares
        # a live event's own old_state/new_state, and a freshly-starting
        # process's first-ever state report for any entity has no old_state
        # at all, so that listener structurally can never see this specific
        # transition. Found live, 2026-07-27: HA Core updates never
        # appeared on the History page at all.
        self._last_installed_version: dict[str, str] = {}
        self._last_installed_store: Store[dict[str, str]] = Store(
            hass, _LAST_INSTALLED_STORAGE_VERSION, _LAST_INSTALLED_STORAGE_KEY
        )
        # entity_id -> the exact latest_version the panel's own "Ready now"
        # button forced ready for, overriding the normal wait-days countdown
        # for that one jump -- lets someone skip the rest of a postponement
        # period they've decided isn't needed for this specific update.
        # Self-clears the moment latest_version
        # moves past the forced version: only ever consulted when it still
        # matches the entity's *current* latest (see _async_cache_active/
        # _recompute_all), so a version bump silently orphans the old
        # record, no explicit cleanup needed here, same reasoning
        # staging_skip.py's own self._skipped already relies on for itself.
        self._force_ready: dict[str, str] = {}
        self._force_ready_store: Store[dict[str, str]] = Store(
            hass, _FORCE_READY_STORAGE_VERSION, _FORCE_READY_STORAGE_KEY
        )
        self._listeners: list[Callable[[], None]] = []
        self._install_listeners: list[InstallListener] = []
        self._unsub_state_changed: Callable[[], None] | None = None
        self._unsub_recheck: Callable[[], None] | None = None
        # A precise, one-off wake-up on top of _unsub_recheck's own
        # _RECHECK_INTERVAL safety net -- see _schedule_next_wakeup's own
        # comment for why.
        self._unsub_next_wakeup: Callable[[], None] | None = None
        # The master pause switch (const.py's CONF_ENABLED) -- the single,
        # shared source of truth install_manager.py/staging_skip.py both
        # read directly (self._coordinator.master_enabled) instead of each
        # keeping its own independently-set copy. Found by review: two
        # hand-synced private copies, each updated from its own call site,
        # could silently disagree if a future settings-apply path ever
        # forgot to notify one of the two managers -- reading one shared
        # flag off the coordinator both already hold a reference to makes
        # that impossible (whichever manager *does* get told about a
        # change updates the one flag the other reads too, even if its own
        # notification was missed).
        self.master_enabled: bool = True
        # Wired up by __init__.py right after both this coordinator and
        # staging_skip.py's StagingSkipManager exist (that manager depends
        # on this coordinator, so can't be passed in at construction time
        # here) -- lets _async_refresh_one tell "we skipped this ourselves,
        # purely to hide a still-postponed update from HA's own update
        # count" apart from "the user skipped this for their own reason",
        # without this module needing to import/depend on that one.
        # Defaults to "never ours" so this coordinator still works
        # standalone (e.g. in tests) without that wiring.
        self._is_own_skip: Callable[[str, str], bool] = lambda entity_id, version: False

    def set_master_enabled(self, enabled: bool) -> None:
        self.master_enabled = enabled

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

    def set_own_skip_checker(self, checker: Callable[[str, str], bool]) -> None:
        self._is_own_skip = checker

    async def async_start(self) -> None:
        # Gathered, not sequential awaits -- fully independent Store reads,
        # found by code review, 2026-07-27.
        available_since, last_installed_version, force_ready = await asyncio.gather(
            self._available_since_store.async_load(),
            self._last_installed_store.async_load(),
            self._force_ready_store.async_load(),
        )
        self._available_since = available_since or {}
        self._last_installed_version = last_installed_version or {}
        self._force_ready = force_ready or {}

        # Subscribe *before* the initial bulk scan, not after -- found via
        # live testing on a real instance (some pending updates never
        # showed up at all). The staggered scan below can easily take
        # several seconds on a large instance (100+ update entities); any
        # update entity whose very first state (another integration finishing
        # its own setup later than ours, e.g.) appeared in that window would
        # be in neither the scan's snapshot nor caught by a listener that
        # wasn't attached yet, and so was silently missed forever. Listening
        # first means the worst case is now a harmless redundant refresh
        # (the scan reaching that same entity a moment later), not a gap.
        self._unsub_state_changed = self.hass.bus.async_listen("state_changed", self._handle_state_changed)
        self._unsub_recheck = async_track_time_interval(self.hass, self._async_periodic_recheck, _RECHECK_INTERVAL)

        for entity_id in self.hass.states.async_entity_ids("update"):
            self._recover_install_across_restart(entity_id)
            await self._async_refresh_one(entity_id)
            await asyncio.sleep(_STARTUP_QUERY_STAGGER)

        # _async_refresh_one above (unlike its own async_refresh_one/
        # _async_handle_changed wrappers) doesn't call _fire_listeners on
        # its own -- without this, _schedule_next_wakeup's own precise
        # wake-up wouldn't actually start covering anything until the first
        # periodic recheck, a real state_changed event, or a settings save
        # happened to fire it, up to _RECHECK_INTERVAL after a fresh
        # restart.
        self._fire_listeners()

    @callback
    def _recover_install_across_restart(self, entity_id: str) -> None:
        """Retroactively fires the install listeners for an install that
        completed entirely while HA was down (see self._last_installed_version's
        own comment for why _handle_state_changed's live event comparison
        can never catch this on its own). Must run before _async_refresh_one
        for this same entity_id -- that call is what advances
        self._last_installed_version to the current value, so this needs to
        compare against the old persisted value first.

        Same call shape as the live path (listener(entity_id, old, new,
        state)), so install_log.py's own listener doesn't need to know
        this ever happened any differently. coordinator.cache is always
        empty for this entity_id at this point (rebuilt from scratch every
        restart, no entry yet), so the listener's own available_since
        naturally comes back None here -- an honest "we don't know", not a
        guess, since HA genuinely wasn't running to observe when this
        update actually became available.

        Known limitation, found by code review, 2026-07-27: for the same
        reason, __init__.py's own _on_install always logs this as a manual
        install, never an auto-install, even if install_manager.py's own
        InstallManager actually dispatched it right before the restart --
        was_auto_installed() reads InstallManager._recently_executed, an
        in-memory-only dict that can't survive a restart any more than
        this coordinator's own un-persisted cache can. Today this is only
        ever *actually* wrong for a non-Core/Supervisor/OS entity that's
        both auto-install-eligible in this integration's own rules and
        happens to need a restart before its own installed_version updates
        (Core/Supervisor/OS themselves are hard-excluded from auto-install
        entirely, so "manual" is always correct for them regardless) --
        narrow enough, and persisting dispatch records across a restart
        invasive enough, that this is left as a documented gap rather than
        fixed here."""
        state = self.hass.states.get(entity_id)
        if state is None:
            return
        new_installed = state.attributes.get("installed_version")
        # _PLACEHOLDER_INSTALLED_VERSION excluded the same way
        # _async_refresh_one's own baseline-advance does (see that
        # constant's own comment for the confirmed Zigbee2MQTT restart
        # quirk this guards against) -- without it, a device that hasn't
        # synced its real firmware version back yet would fire a bogus
        # "install" event claiming the device regressed from its real
        # previous version down to the placeholder.
        if not new_installed or new_installed == _PLACEHOLDER_INSTALLED_VERSION:
            return
        old_installed = self._last_installed_version.get(entity_id)
        if old_installed is not None and old_installed != new_installed:
            self._fire_install_listeners(entity_id, old_installed, new_installed, state)

    def _fire_install_listeners(self, entity_id: str, old_installed: str, new_installed: str, state: State) -> None:
        """The one place every install listener actually gets called, shared
        by the live path (_handle_state_changed) and the restart-recovery
        path (_recover_install_across_restart above) -- found by review,
        these previously each had their own identical `for listener in
        list(self._install_listeners): listener(...)` loop."""
        for listener in list(self._install_listeners):
            listener(entity_id, old_installed, new_installed, state)

    def _fire_listeners(self) -> None:
        """The one place every plain (no-argument) listener actually gets
        called -- found by code review, 2026-07-27: this exact `for listener
        in list(self._listeners): listener()` loop was independently
        duplicated at three call sites (_async_periodic_recheck,
        async_update_rules, _async_handle_changed), mirroring the same
        duplication _fire_install_listeners above was already extracted to
        fix for the install-listener list. Also the one place
        _schedule_next_wakeup gets refreshed, for the same reason -- every
        one of those call sites just finished a recompute, exactly when the
        soonest still-pending deadline might have changed."""
        for listener in list(self._listeners):
            listener()
        self._schedule_next_wakeup()

    def _schedule_next_wakeup(self) -> None:
        """A precise, one-off wake-up at the earliest ready_at among every
        currently "waiting" entity, on top of _unsub_recheck's own
        _RECHECK_INTERVAL periodic safety net.

        Not for display accuracy -- status_now computes that fresh on every
        read regardless of when this last ran, so nothing shown in the
        panel can ever be stale (see its own docstring). This is purely
        about how promptly install_manager.py/staging_skip.py/sensor.py
        (the real, action-taking consumers of self.cache's own stored
        status, all synchronized via self._listeners) actually notice a
        change and do something about it -- announcing/auto-installing, or
        un-hiding a postponed update, right around the moment it's actually
        due, instead of up to _RECHECK_INTERVAL late. Still worth keeping
        even once storing status for display purposes was no longer
        needed, 2026-08-12: recomputing right at each update's own known,
        already-calculated deadline is strictly better than only ever
        recomputing on a coarse periodic interval, for the same reason a
        calendar reminder beats a "check every 15 minutes" habit.

        Cancels and recomputes from scratch every call instead of only
        extending/shortening the existing one, simplest correct way to
        always reflect whatever the soonest deadline currently is,
        including one a settings save just changed."""
        if self._unsub_next_wakeup is not None:
            self._unsub_next_wakeup()
            self._unsub_next_wakeup = None

        ready_ats = [
            parsed
            for cached in self.cache.values()
            if cached["status"] == "waiting" and cached.get("ready_at")
            and (parsed := dt_util.parse_datetime(cached["ready_at"])) is not None
        ]
        if not ready_ats:
            return
        self._unsub_next_wakeup = async_track_point_in_time(
            self.hass, self._async_scheduled_recompute, min(ready_ats)
        )

    @callback
    def _async_scheduled_recompute(self, now: datetime) -> None:
        self._unsub_next_wakeup = None
        self._recompute_all(now)
        self._fire_listeners()

    @callback
    def async_stop(self) -> None:
        if self._unsub_state_changed is not None:
            self._unsub_state_changed()
            self._unsub_state_changed = None
        if self._unsub_recheck is not None:
            self._unsub_recheck()
            self._unsub_recheck = None
        if self._unsub_next_wakeup is not None:
            self._unsub_next_wakeup()
            self._unsub_next_wakeup = None

    def _recompute_all(self, now: datetime) -> None:
        """The actual status/remaining_seconds/auto_install_excluded
        recompute, from already-cached facts (installed_version/
        latest_version/available_since don't change here) -- shared by
        async_update_rules (new rules) and _async_periodic_recheck (same
        rules, just time having passed).

        Skips entries already cached as "skipped" -- that status isn't
        derived from staging rules at all (see _cache_skipped), it's a
        direct reflection of HA's own skipped_version state; recomputing
        staging over it here would silently overwrite it back to a
        ready/waiting/blocked verdict on every settings save or periodic
        recheck, even though the entity's real HA state never actually
        changed (still genuinely skipped). Only a real _async_refresh_one,
        triggered by an actual state_changed event, should ever transition
        an entry in or out of "skipped" -- with one exception: if
        is_own_skip now recognizes this exact entity/version as our own
        automatic skip, it falls through to a normal staging verdict below
        instead of staying protected. Found live: staging_skip.py's own
        _async_skip has a narrow race window (its own docstring/comment
        explains it) where the entity's state_changed event -- and so this
        cache's very first "skipped" classification -- can land before its
        internal record was written, permanently misclassifying an
        auto-skip as a real user one (that guard above alone would leave it
        stuck that way forever, since its own state never changes again).
        This check heals that on the very next recompute instead of
        requiring a restart."""
        # Catches an entity _async_refresh_one's own _CACHE_UNAVAILABLE_GRACE
        # left alone on its one state_changed event, but that then never
        # actually recovered and also never fired another such event to be
        # re-checked by (a plain, no-op-attribute unavailable state usually
        # doesn't keep firing state_changed on its own) -- this periodic
        # pass is the safety net that still gets to it eventually, same
        # "eventually consistent" role _async_recheck_stuck_installs already
        # plays for rollout_manager.py's own equivalent grace period.
        stale = [
            entity_id
            for entity_id in self.cache
            if (state := self.hass.states.get(entity_id)) is not None
            and state.state == "unavailable"
            and now - state.last_changed >= _CACHE_UNAVAILABLE_GRACE
        ]
        for entity_id in stale:
            del self.cache[entity_id]

        for entity_id, cached in self.cache.items():
            if cached["status"] == "skipped":
                if not self._is_own_skip(entity_id, cached["latest_version"]):
                    continue
            cached.update(self._derive_status_fields(entity_id, cached, now))
            cached["auto_install_excluded"] = _is_excluded_from_auto_install(
                entity_id, self.excluded_entities
            )

    @callback
    def _async_periodic_recheck(self, now: datetime) -> None:
        self._recompute_all(now)
        self._fire_listeners()

    async def async_update_rules(
        self,
        rules: StagingRules,
        excluded_entities: frozenset[str] | None = None,
        schedule: PostponementSchedule | None = None,
    ) -> None:
        """Applies newly-saved staging rules (and, since 2026-07-16, the
        user's own excluded-entities picks, and now the postponement
        schedule too) without a full entry reload (see __init__.py's
        update_listener): the already-cached installed_version/
        latest_version/available_since facts don't change just because the
        settings did, only the derived ready/waiting/blocked verdict (and
        now also auto_install_excluded) does -- cheap to recompute in place,
        no recorder round-trip needed. Found live: the Updates/History tabs
        briefly went empty after every settings save, while the old
        reload-based approach tore down and rebuilt the whole cache from
        scratch (a multi-second, staggered bulk scan)."""
        self.rules = rules
        if excluded_entities is not None:
            self.excluded_entities = excluded_entities
        if schedule is not None:
            self.schedule = schedule
            self._schedule_active = any(day.enabled for day in schedule.days)
        self._recompute_all(dt_util.utcnow())
        self._fire_listeners()

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
            self._fire_install_listeners(entity_id, old_installed, new_installed, new_state)

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
        self._fire_listeners()

    async def async_refresh_one(self, entity_id: str) -> None:
        """Public entry point for a caller that changed something
        is_own_skip's own answer for this entity depends on (see
        websocket_api.py's skip handler) and wants this coordinator's
        cached classification to catch up right now, rather than waiting
        for a real state_changed event or the periodic recheck -- calling
        the real update.skip service again when skipped_version already
        equals latest_version is a harmless no-op from HA's own
        perspective, so no state_changed event fires to trigger this on
        its own."""
        await self._async_handle_changed(entity_id)

    async def async_force_ready(self, entity_id: str, to_version: str) -> None:
        """The panel's own "Ready now" button (see self._force_ready's own
        comment) -- records the override, persists it, then reuses
        async_refresh_one above to recompute this one entity's cache entry
        right away, the same way skip/unskip already do: setting an
        override doesn't itself produce a real state_changed event the way
        a genuine update.skip call does, so nothing else would otherwise
        tell this coordinator to look again."""
        self._force_ready[entity_id] = to_version
        await self._force_ready_store.async_save(self._force_ready)
        await self.async_refresh_one(entity_id)

    async def _async_refresh_one(self, entity_id: str) -> None:
        state = self.hass.states.get(entity_id)
        if state is None:
            self.cache.pop(entity_id, None)
            if self._available_since.pop(entity_id, None) is not None:
                await self._available_since_store.async_save(self._available_since)
            if self._last_installed_version.pop(entity_id, None) is not None:
                self._last_installed_store.async_delay_save(lambda: self._last_installed_version, 1.0)
            return

        # Advances the restart-recovery baseline (see
        # _recover_install_across_restart) to whatever's live right now,
        # regardless of "on"/"off"/skipped below -- this only cares about
        # installed_version itself, not whether an update is pending.
        # Delay-saved, not awaited immediately: this runs on every relevant
        # state change, not just installs, and a lost write only costs a
        # duplicate retroactive fire after a crash landing in that exact
        # window, not a wrong user-visible decision (same risk already
        # accepted for community_verdict.py's own cache).
        live_installed = state.attributes.get("installed_version")
        # _PLACEHOLDER_INSTALLED_VERSION excluded explicitly, not just
        # falsy-checked (see that constant's own comment) -- a plain
        # `if live_installed:` treats that non-empty string as a real
        # version, permanently poisoning this restart-recovery baseline
        # with it; the next restart then sees a real version where this
        # persisted placeholder was expected, concludes an install
        # silently completed while HA was down, and fires a bogus
        # install-log entry for it.
        if (
            live_installed
            and live_installed != _PLACEHOLDER_INSTALLED_VERSION
            and self._last_installed_version.get(entity_id) != live_installed
        ):
            self._last_installed_version[entity_id] = live_installed
            self._last_installed_store.async_delay_save(lambda: self._last_installed_version, 1.0)

        # HA's own update entities are always exactly "on" (an update is
        # available) or "off" -- "off" normally means genuinely up to
        # date, but also covers a *skipped* update (homeassistant/
        # components/update/__init__.py's own state logic: latest_version
        # == skipped_version reports "off" too, confirmed against source).
        if state.state != "on":
            if (
                state.state == "unavailable"
                and entity_id in self.cache
                and dt_util.utcnow() - state.last_changed < _CACHE_UNAVAILABLE_GRACE
            ):
                # See _CACHE_UNAVAILABLE_GRACE's own comment -- leave
                # whatever's already cached alone rather than evicting it on
                # what's likely just a transient blip.
                return
            current = state.attributes.get("installed_version")
            latest = state.attributes.get("latest_version")
            skipped_version = state.attributes.get("skipped_version")
            # `current` guarded explicitly, not just implied by `current !=
            # latest` -- that comparison is also True whenever `current` is
            # None (a real, reachable state for an entity that hasn't
            # reported installed_version yet), and both branches below
            # eventually call classify_version_size, which unconditionally
            # calls .strip() on it. The sibling "on" branch further down
            # already guards the same way for the same reason.
            if latest and current and skipped_version == latest and current != latest:
                if self._is_own_skip(entity_id, latest):
                    # staging_skip.py's own doing -- purely a mechanism for
                    # hiding a still-postponed update from HA's own update
                    # count, not a fact the user should see reflected here
                    # at all (direct user feedback: "skipped by us ==
                    # postponed" -- it should read exactly as if state were
                    # still "on"). Evaluate normally, not as skipped.
                    await self._async_cache_active(entity_id, state, current, latest)
                else:
                    # A real, user-initiated skip (HA's own UI, or our own
                    # Skip button) -- surface it distinctly instead of
                    # treating it identically to nothing pending at all,
                    # see the panel's own "Skipped" group.
                    self._cache_skipped(entity_id, state, current, latest)
                return
            self.cache.pop(entity_id, None)
            return

        current = state.attributes.get("installed_version")
        latest = state.attributes.get("latest_version")
        if not current or not latest:
            if entity_id in self.cache:
                # state.state == "on" already confirms this is a genuine,
                # still-pending update -- installed_version/latest_version
                # going momentarily missing here isn't evidence it stopped
                # being one, only that this one state_changed event's own
                # attributes happened to be incomplete (found live,
                # 2026-08-10: a Zigbee2MQTT device's own update entity, mid
                # firmware flash, briefly reported this way while dozens of
                # other entities were being force-polled at once by the
                # panel's own refresh button -- plausibly enough MQTT
                # traffic at once to coalesce/truncate this one device's own
                # payload). Unlike the state.state != "on" branches above,
                # there's no unavailable-style grace *period* to apply here
                # (last_changed wouldn't even move, state.state itself never
                # changed) -- simply keep whatever's already cached instead
                # of evicting it on a single incomplete reading; a later,
                # complete state_changed event naturally corrects it via a
                # normal _async_cache_active call.
                return
            self.cache.pop(entity_id, None)
            return
        await self._async_cache_active(entity_id, state, current, latest)

    async def _async_get_available_since(self, entity_id: str, latest_version: str) -> datetime:
        """The authoritative "when did `latest_version` first become this
        entity's latest_version", read from self._available_since (see
        __init__'s own comment) whenever it already has a record for this
        exact version, so a later restart/availability blip/integration
        reload can never quietly re-derive a different answer for a
        version we've already anchored. Only falls through to
        _async_available_since's best-effort recorder lookup the first
        time this entity/version pair is ever seen, then remembers that
        result from here on: a one-time backfill, not a lookup repeated
        on every refresh."""
        record = self._available_since.get(entity_id)
        if record is not None and record.get("version") == latest_version:
            parsed = dt_util.parse_datetime(record.get("since", ""))
            if parsed is not None:
                return parsed

        available_since = await _async_available_since(self.hass, entity_id, latest_version)
        self._available_since[entity_id] = {"version": latest_version, "since": available_since.isoformat()}
        await self._available_since_store.async_save(self._available_since)
        return available_since

    def _staging_result(
        self, entity_id: str, latest: str, size: str, available_since: datetime, now: datetime, rules: StagingRules
    ) -> StagingResult:
        """The panel's own "Ready now" button (see self._force_ready's own
        comment) overrides the normal wait-days verdict for this one
        entity/version pair -- shared by _staged_result's own two callers
        (_recompute_all and _async_cache_active) via that method, found by
        code review, 2026-08-10 (both used to inline the exact same
        three-line branch independently)."""
        if self._force_ready.get(entity_id) == latest:
            return StagingResult("ready", None)
        return evaluate_staging(size, available_since, now, rules)

    def _staged_result(
        self, entity_id: str, latest: str, size: str, available_since: datetime, now: datetime, rules: StagingRules
    ) -> StagingResult:
        """_staging_result's own wait-based verdict, with the postponement
        schedule (issue #4) composed on top of it -- shared by
        _recompute_all and _async_cache_active, same reason _staging_result
        itself is shared (see its own docstring). Single-sourced here, not
        left to each caller to guard + look up wait_for_size + call
        _apply_schedule_gate itself: found by code review, 2026-08-12, that
        exact three-line block had drifted back into being duplicated at
        both call sites once _apply_schedule_gate's own signature grew a
        `wait_deadline` parameter -- the same shape of duplication
        _staging_result was already extracted once to fix."""
        result = self._staging_result(entity_id, latest, size, available_since, now, rules)
        if result.status not in ("ready", "waiting"):
            # "blocked" needs a manual decision regardless of any schedule;
            # "skipped" never reaches here at all (see _recompute_all's own
            # guard, and _async_cache_active never produces it either).
            return result
        if self._force_ready.get(entity_id) == latest:
            # The "Ready now" override (_staging_result's own force_ready
            # branch, a couple lines up) is a deliberate, explicit decision
            # that this one jump doesn't need to wait any further at all --
            # bypasses the schedule gate entirely, the same way it already
            # bypasses the wait-days period itself, rather than running the
            # forced-ready result through it. Found by code review,
            # 2026-08-12: an earlier version of this still ran the forced
            # result through _apply_schedule_gate (using `now` as the wait
            # deadline instead of available_since + wait), which stopped
            # re-deriving the original, now-irrelevant wait period, but
            # could still downgrade the override right back to "waiting"
            # whenever the schedule itself simply wasn't open yet -- the
            # override existing specifically to skip past that too, not
            # just past the wait-days math.
            return result
        wait_deadline = available_since + wait_for_size(rules, size)
        return self._apply_schedule_gate(result, wait_deadline, now)

    def _apply_schedule_gate(self, result: StagingResult, wait_deadline: datetime, now: datetime) -> StagingResult:
        """The actual schedule composition -- called only by _staged_result
        above, already past its own "ready"/"waiting" guard, so `result` is
        never "blocked"/"skipped" here. Split out from _staged_result on its
        own (rather than inlined) purely so its own considerable amount of
        reasoning about *why* `wait_deadline`/`as_local` below are correct
        doesn't have to live inside _staged_result's own, shorter docstring.

        Found live, 2026-08-11: a freshly-discovered/refreshed update
        (going through _async_cache_active, not _recompute_all) showed its
        raw wait-days deadline, ignoring the schedule entirely, for up to
        _RECHECK_INTERVAL until the next periodic recompute caught it --
        the actual reason this is shared rather than only ever called from
        _recompute_all.

        `wait_deadline`, not `now` -- this size's own wait period ending is
        a fixed fact about this update, the same value every time this
        happens to be evaluated for it, regardless of whether that's before
        or after it actually elapses; found live, 2026-08-11/12, after two
        reverted attempts that each compared the schedule against `now`
        directly (whatever moment this happens to run at, a periodic
        recheck or the precise-wakeup timer) instead: `now` is never
        deterministic relative to a schedule's own configured time (a
        periodic check essentially never lands on the exact instant, and by
        the time staging itself already says "ready" -- wait already
        elapsed -- "now" has no memory of when that actually happened
        anymore), so the schedule's own answer kept depending on incidental
        recompute timing rather than on anything about the update itself.
        See next_allowed_ready's own docstring for the full account and
        exactly what "resolved against wait_deadline" means.

        as_local, not the bare (UTC) wait_deadline -- the schedule's own
        day/time rules are the user's own wall-clock picks in the panel (a
        plain time selector, no timezone of its own), so "Wednesday 10:00"
        means 10:00 in the instance's own local timezone, not UTC; comparing
        naive local times against a bare UTC instant silently shifts both
        the hour and, near midnight, sometimes the weekday itself. The
        result comes back local-aware; comparing/subtracting it against
        `now` (UTC) still works correctly regardless, since aware-datetime
        arithmetic is timezone-independent. self._schedule_active checked
        first, before any of that -- the default, untouched-by-any-install
        state is every day disabled, so most installs would otherwise pay
        the timezone conversion and 8-day scan below for every cached
        entity, on every periodic recheck and every per-entity refresh, for
        a result that's always thrown away."""
        if not self._schedule_active:
            return result
        target = next_allowed_ready(self.schedule, dt_util.as_local(wait_deadline))
        if target is None or target <= now:
            # None: schedule doesn't restrict anything (checked above, kept
            # as next_allowed_ready's own contract too). target <= now: its
            # own resolved instant has already arrived in real time, same
            # verdict staging itself already gave -- nothing left to gate.
            return result
        return StagingResult("waiting", target - now)

    def _derive_status_fields(self, entity_id: str, cached: dict, now: datetime) -> dict:
        """status/remaining_seconds/ready_at, derived fresh from `cached`'s
        own already-known facts (latest_version/version_size/available_since
        -- never itself time-dependent, only ever changes on a real
        state_changed event) and whatever `now` the caller passes in.

        Two callers, two different reasons to call this: _recompute_all
        below calls it (and writes the result back into `cached`) so
        install_manager.py/staging_skip.py/sensor.py, all synchronized via
        self._listeners right after that same recompute, see an accurate
        status without needing to derive it themselves. status_now calls it
        completely independently, fresh, at whatever instant a caller
        actually asks -- this is the one that matters for display: found
        live, 2026-08-11/12, that storing a derived remaining_seconds/
        ready_at and only refreshing it periodically (however often, and
        however precisely-timed) is structurally incompatible with a
        display that's read at arbitrary, unrelated moments -- the very
        first fix here (_cache_timing_fields's own ready_at) computed it
        once, but still only *inside* a periodic recompute; the pill still
        drifted between recomputes, then a follow-up added a precise
        per-entity wakeup timer to shrink that gap, which only shrank it,
        never eliminated it, and added real scheduling complexity for a
        problem that a stored value can never actually stop having.
        `available_since + wait_days` (and the schedule on top of it) is
        the same fixed calculation regardless of when it's evaluated, so
        there's nothing to gain from ever storing its answer -- only
        something to lose (staleness) every time it's read after having
        been stored."""
        available_since = dt_util.parse_datetime(cached["available_since"])
        result = self._staged_result(
            entity_id, cached["latest_version"], cached["version_size"], available_since, now, self.rules
        )
        return {"status": result.status, **_cache_timing_fields(result, now)}

    def status_now(self, cached: dict, now: datetime | None = None) -> dict:
        """The current status/remaining_seconds/ready_at for one cache
        entry, computed fresh from this exact instant -- not whatever
        happens to already be stored in it, which can be anywhere up to
        _RECHECK_INTERVAL stale. See _derive_status_fields's own docstring
        for why storing them at all was the actual bug, not just how often
        they got refreshed.

        `now` defaults to a fresh dt_util.utcnow() per call, but a caller
        deriving several entities in the same pass (export_entry's own
        callers, websocket_api.py's _handle_updates and diagnostics.py, each
        looping over every cached entity for one request) should compute it
        once and pass it through instead -- these are all meant to describe
        "the state of things at this one moment", not each entity read at
        its own, slightly different instant.

        "skipped" is left exactly as stored, not re-derived -- it's a
        direct reflection of HA's own skipped_version state (see
        _recompute_all's own matching guard), not a staging-timing verdict
        _derive_status_fields would know how to reproduce; calling it for a
        genuinely skipped entity would wrongly overwrite "skipped" with
        whatever ready/waiting/blocked the wait-days math alone says."""
        if cached["status"] == "skipped":
            return {"status": "skipped", **_NO_TIMING_FIELDS}
        return self._derive_status_fields(cached["entity_id"], cached, now or dt_util.utcnow())

    def export_entry(self, cached: dict, now: datetime | None = None) -> dict:
        """One cache entry's own facts, with status/remaining_seconds/
        ready_at overridden by status_now's own fresh derivation -- the one
        place that merge happens, shared by websocket_api.py's own
        _handle_updates and diagnostics.py, which both need exactly this
        same "cached facts + fresh verdict" shape for their own response."""
        return {**cached, **self.status_now(cached, now)}

    async def _async_cache_active(self, entity_id: str, state: State, current: str, latest: str) -> None:
        size = classify_version_size(current, latest)
        now = dt_util.utcnow()
        # Uses this entry's actual configured rules (settings panel), not
        # always the hardcoded defaults -- a user may have given "large" a
        # real wait instead of "always blocked". Only skip
        # the recorder query when the *configured* wait for this size is
        # None, since only then can available_since not change the answer.
        rules = self.rules
        configured_wait = wait_for_size(rules, size)
        if configured_wait is None:
            available_since = now
        else:
            available_since = await self._async_get_available_since(entity_id, latest)
        # available_since is still computed normally above either way, it's
        # a real fact used elsewhere (History); only the derived status/
        # remaining is overridden, see _staging_result's own comment.
        result = self._staged_result(entity_id, latest, size, available_since, now, rules)
        # Some update entities (e.g. firmware that must be flashed manually)
        # only ever report that a newer version exists, with no install
        # action at all -- ready/waiting/blocked is still meaningful for
        # "should you move to this version", but install_manager.py's
        # auto-install must gate on this: never call update.install on an
        # entity that doesn't support it.
        installable = bool(state.attributes.get("supported_features", 0) & UpdateEntityFeature.INSTALL)
        # Whatever's already known, synchronously, no fetch: found by
        # review, this used to await the real lookup right here, serializing
        # a network round-trip (on a cache miss/expiry) into every single
        # entity's staging-status write below, even though the verdict is
        # purely cosmetic and never gates this decision. A real refresh (if
        # needed) is fired as its own background task instead, see
        # _async_refresh_community_verdict.
        community_verdict = (
            self._community_verdict_manager.peek_cached_verdict(entity_id, latest, current)
            if self._community_verdict_manager is not None
            else None
        )
        # Same reasoning as community_verdict above: whatever's already
        # known, synchronously, refreshed as its own background task below.
        trusted_vote, trusted_voters_matched = (
            self._community_verdict_manager.peek_cached_trusted_vote(entity_id, latest, current)
            if self._community_verdict_manager is not None
            else (None, [])
        )
        if self._community_verdict_manager is not None:
            self.hass.async_create_task(
                self._async_refresh_community_verdict(
                    entity_id, state.attributes.get("release_url"), latest, current
                )
            )
        self.cache[entity_id] = {
            "entity_id": entity_id,
            "installed_version": current,
            "latest_version": latest,
            "version_size": size,
            "status": result.status,
            **_cache_timing_fields(result, now),
            "installable": installable,
            # Corrected here (not left to the frontend to read state.attributes
            # itself) specifically for Core -- see corrected_release_url's own
            # docstring for the real bug this fixes: Core's own native
            # release_url is a fixed "always latest" URL, never version-
            # specific, useless for the GitHub release-notes fallback fetch
            # and actively wrong once a newer version comes out. A no-op for
            # every other entity (OS/Supervisor/anything else), returns
            # whatever state already had.
            "release_url": corrected_release_url(entity_id, state.attributes.get("release_url"), latest),
            # Exposed mainly so the recorder lookup above can actually be
            # checked by hand (diagnostics download) instead of only being
            # inferable from status/remaining_seconds.
            "available_since": available_since.isoformat(),
            # Core/Supervisor/HAOS, plus whatever the user picked themselves:
            # always manual, regardless of the size/auto-install settings --
            # install_manager.py checks this before ever auto-installing.
            # Doesn't change size/status here, those stay informational.
            "auto_install_excluded": _is_excluded_from_auto_install(entity_id, self.excluded_entities),
            # True only for a "waiting" entity that's *also* currently
            # hidden from HA's own update count via staging_skip.py's own
            # auto-skip (direct user feedback, 2026-07-17: the distinction
            # between "we skipped this" and "the user skipped this" was
            # only ever inspectable by reading is_own_skip's own logic --
            # exposed here directly instead, on the summary sensor and the
            # panel's websocket payload alike, for debugging without
            # needing either).
            "hidden_by_update_manager": bool(
                state.attributes.get("skipped_version") == latest and self._is_own_skip(entity_id, latest)
            ),
            # None when not HACS-identified (see community_verdict.py) or
            # not yet rated, never a placeholder/empty object. The panel
            # renders no badge at all for either case, matching this
            # feature's own read-only-first scope (see community_verdict.py).
            "community_verdict": community_verdict,
            # (verdict, matched usernames) from the configured trusted-
            # voters list (see const.py's CONF_TRUSTED_VOTERS), already
            # aggregated -- (None, []) when nobody's configured, or none of
            # them has voted on this exact version. install_manager.py's
            # own effective_auto_install_state (announcer.py) reads
            # trusted_vote to decide eligibility; the panel reads both to
            # explain a block on the still-pending update itself.
            "trusted_vote": trusted_vote,
            "trusted_voters_matched": trusted_voters_matched,
        }

    async def _async_refresh_community_verdict(
        self,
        entity_id: str,
        release_url: str | None,
        latest: str,
        installed_version: str,
        *,
        force: bool = False,
    ) -> None:
        """Its own task, not awaited inline by _async_cache_active (see that
        method's own comment): patches this entity's cache entry once the
        real lookup resolves, but only if that entry still exists and still
        refers to the exact same jump (both latest_version AND
        installed_version -- entity_id's own cache entry may have moved on,
        e.g. a newer version, no longer pending at all, or even an
        intermediate manual install changing installed_version underneath
        this same latest_version, by the time this background fetch
        finishes). Patches trusted_vote/trusted_voters_matched too --
        async_get_verdict fetches and caches both in the same call, see
        community_verdict.py's own docstring.

        force=True bypasses CommunityVerdictManager's own hour-long
        freshness window -- see async_force_refresh_community_verdicts
        below, the only caller that ever passes this."""
        assert self._community_verdict_manager is not None
        verdict = await self._community_verdict_manager.async_get_verdict(
            entity_id, release_url, latest, installed_version, force=force
        )
        trusted_vote, trusted_voters_matched = self._community_verdict_manager.peek_cached_trusted_vote(
            entity_id, latest, installed_version
        )
        cached = self.cache.get(entity_id)
        if (
            cached is not None
            and cached.get("latest_version") == latest
            and cached.get("installed_version") == installed_version
        ):
            cached["community_verdict"] = verdict
            cached["trusted_vote"] = trusted_vote
            cached["trusted_voters_matched"] = trusted_voters_matched

    async def async_force_refresh_community_verdicts(self) -> None:
        """Bypasses CommunityVerdictManager's own hour-long freshness window
        for every currently-active entity, so the panel's manual refresh
        button can guarantee genuinely fresh community-votes data instead of
        silently showing whatever was cached up to an hour ago -- direct
        user feedback, 2026-07-25 ("als ik op de refresh knop druk wil ik
        dat hij ook de meest recente info van de votes naar binnen haalt").

        Concurrent, not sequential: raw.githubusercontent.com reads aren't
        rate-limited (see community_verdict.py's own docstring), and this is
        a rare, deliberate, user-initiated action, not a background poll --
        same reasoning already applied to the per-dialog verdict_for_version
        fetch. self.cache is only ever entities with something currently
        pending (see _async_refresh_one's own pop-when-not-active logic), so
        this is already a naturally bounded set, not every tracked entity.

        Snapshotted via list(...) before gathering: an unrelated
        state_changed event could mutate self.cache concurrently with this
        (e.g. an install finishing mid-refresh), and iterating a dict while
        something else mutates it would raise."""
        if self._community_verdict_manager is None:
            return

        async def _refresh_one(entity_id: str, cached: dict[str, Any]) -> None:
            state = self.hass.states.get(entity_id)
            if state is None:
                return
            await self._async_refresh_community_verdict(
                entity_id,
                state.attributes.get("release_url"),
                cached["latest_version"],
                cached["installed_version"],
                force=True,
            )

        await asyncio.gather(*(_refresh_one(entity_id, cached) for entity_id, cached in list(self.cache.items())))

    def _cache_skipped(self, entity_id: str, state: State, current: str, latest: str) -> None:
        # No staging computation here (state itself is "off", not "on" --
        # never ran through _async_cache_active), so no remaining_seconds/
        # real available_since either; available_since falls back to
        # whatever was last known, or now if this entity's never been
        # cached before, same conservative default _async_available_since
        # itself falls back to.
        previous = self.cache.get(entity_id)
        available_since = previous["available_since"] if previous else dt_util.utcnow().isoformat()
        self.cache[entity_id] = {
            "entity_id": entity_id,
            "installed_version": current,
            "latest_version": latest,
            "version_size": classify_version_size(current, latest),
            "status": "skipped",
            **_NO_TIMING_FIELDS,
            "installable": bool(state.attributes.get("supported_features", 0) & UpdateEntityFeature.INSTALL),
            # Same correction as _async_cache_active's own -- see
            # corrected_release_url's own docstring. Every cache entry gets
            # the same shape (see this method's own comment further down).
            "release_url": corrected_release_url(entity_id, state.attributes.get("release_url"), latest),
            "available_since": available_since,
            "auto_install_excluded": _is_excluded_from_auto_install(entity_id, self.excluded_entities),
            # Always False here -- reaching _cache_skipped at all already
            # means the caller's own is_own_skip check said this isn't
            # ours (see _async_refresh_one). See _async_cache_active's own
            # comment for what this field is for.
            "hidden_by_update_manager": False,
            # Not fetched for a skipped entity (this method isn't async, and
            # a skipped/postponed row isn't this slice's target anyway),
            # key still present so every cache entry has the same shape,
            # see _async_cache_active's own comment.
            "community_verdict": previous.get("community_verdict") if previous else None,
        }
