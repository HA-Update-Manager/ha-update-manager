"""Owns the one shared computation of "how should each pending update be
staged right now". Built once per config entry and read by both the summary
sensor (a cheap debug view, see FUTURE.md) and, eventually, the websocket API
Phase 2's panel will use -- neither should duplicate this refresh logic or
the recorder lookups it can trigger.

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

from homeassistant.components.update import UpdateEntityFeature
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import EventStateChangedData, async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BIG_WAIT_DAYS,
    CONF_EXCLUDED_ENTITIES,
    CONF_MEDIUM_WAIT_DAYS,
    CONF_SMALL_WAIT_DAYS,
    PROFILE_BALANCED,
    PROFILE_PRESETS,
)
from .semver import classify_version_size
from .staging import StagingRules, evaluate_staging, wait_for_size

_LOGGER = logging.getLogger(__name__)

# Same lookback window previous-state-tracker's config_flow.py already uses
# for its own best-effort recorder history lookup.
_HISTORY_LOOKBACK = timedelta(days=30)

# Home Assistant Core/Supervisor/OS's own update entities, identified by
# their unique_id (verified against homeassistant/components/hassio/
# entity.py's HassioCoreEntity/HassioSupervisorEntity/HassioOSEntity --
# f"home_assistant_{core,supervisor,os}_{ATTR_VERSION_LATEST}", and
# ATTR_VERSION_LATEST = "version_latest" per hassio/const.py). Matched by
# unique_id rather than by platform == "hassio": that platform also
# provides regular add-ons' update entities, which are a different,
# instelbaar category (see FUTURE.md), not this hard exception.
_HARD_EXCLUDED_UNIQUE_IDS = frozenset(
    {
        "home_assistant_core_version_latest",
        "home_assistant_supervisor_version_latest",
        "home_assistant_os_version_latest",
    }
)

# A registry entry's unique_id is whatever it was when first created, not
# whatever today's hassio/entity.py would generate -- it doesn't get
# migrated just because the integration's own code changed since. Found
# live: a real instance's Core/Supervisor/OS update entities didn't match
# _HARD_EXCLUDED_UNIQUE_IDS at all, despite that matching current source.
# These conventional entity_ids are the fallback for exactly that drift --
# not the primary check (entity_id can, in the abstract, be renamed, unique_id
# can't), but nobody actually renames these three in practice, so it's a
# safe net for whatever unique_id scheme a given instance's registry
# happens to still be carrying.
_HARD_EXCLUDED_ENTITY_IDS = frozenset(
    {
        "update.home_assistant_core_update",
        "update.home_assistant_supervisor_update",
        "update.home_assistant_operating_system_update",
    }
)


def _matches_hard_exclusion(entity_id: str, unique_id: str | None) -> bool:
    return entity_id in _HARD_EXCLUDED_ENTITY_IDS or unique_id in _HARD_EXCLUDED_UNIQUE_IDS


def _is_hard_excluded_from_auto_install(hass: HomeAssistant, entity_id: str) -> bool:
    """Core/Supervisor/HAOS always stay manual, never auto-install,
    regardless of any setting -- decided 2026-07-15, see FUTURE.md: the
    impact of a misser here is the whole HA instance, not one integration/
    add-on/device. Still shown normally otherwise (real size classification,
    a real ready/waiting/blocked status) -- this only ever gates
    install_manager.py's auto-install, never the informational display."""
    entry = er.async_get(hass).async_get(entity_id)
    return _matches_hard_exclusion(entity_id, entry.unique_id if entry else None)


def hard_excluded_entity_ids(hass: HomeAssistant) -> list[str]:
    """The real entity_ids (if these entities exist on this instance at all)
    behind _HARD_EXCLUDED_UNIQUE_IDS -- exposed via websocket_api.py's
    get_settings so the panel's excluded-entities picker can show *which*
    entities are always excluded regardless of what's selected there
    (direct user feedback: the helper text said so, but nothing in the
    picker itself showed them, and they can't be added/removed from that
    list anyway since this exclusion doesn't come from it).

    Called on every settings-tab load/save, so this tries the 3 known
    conventional entity_ids directly (O(1) each via the registry's own
    index) rather than scanning every entity on the instance; only the
    rare drift case (see _HARD_EXCLUDED_ENTITY_IDS's own comment -- a
    conventional entity_id not actually present under that exact id) falls
    back to a full scan, and only for whatever wasn't already found."""
    registry = er.async_get(hass)
    found: set[str] = set()
    remaining_unique_ids = set(_HARD_EXCLUDED_UNIQUE_IDS)
    for entity_id in _HARD_EXCLUDED_ENTITY_IDS:
        entry = registry.async_get(entity_id)
        if entry is not None:
            found.add(entity_id)
            remaining_unique_ids.discard(entry.unique_id)
    if remaining_unique_ids:
        for entry in registry.entities.values():
            if entry.unique_id in remaining_unique_ids:
                found.add(entry.entity_id)
    return sorted(found)


def _is_excluded_from_auto_install(hass: HomeAssistant, entity_id: str, excluded_entities: frozenset[str]) -> bool:
    """The hard Core/Supervisor/HAOS exclusion, plus whatever the user
    picked themselves on the settings screen (direct user feedback: expected
    a way to add their own entities to the same always-manual behaviour, not
    just the 3 hardcoded ones). Same rule either way: still shown normally
    in Updates/Historie, install_manager.py just never auto-installs it."""
    return _is_hard_excluded_from_auto_install(hass, entity_id) or entity_id in excluded_entities


def excluded_entities_from_options(options: dict) -> frozenset[str]:
    return frozenset(options.get(CONF_EXCLUDED_ENTITIES, []))

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
    back to the "balanced" profile's own numbers for anything not set yet
    (e.g. before the settings have ever been saved) -- not staging.py's own
    DEFAULT_RULES, whose big_wait=None means "always blocked". Every real
    profile (const.py's PROFILE_PRESETS) gives "big" a real, finite wait, so
    a freshly-created config entry (options == {}) should read exactly like
    a freshly-saved "balanced" profile, not like a deliberate "block all
    major updates forever" choice nobody actually made. Fixed 2026-07-16:
    found live -- a brand new install showed a major update as blocked/red
    before anyone had ever opened the settings tab."""
    balanced = PROFILE_PRESETS[PROFILE_BALANCED]

    def _wait(days_key: str) -> timedelta:
        return timedelta(days=options.get(days_key, balanced[days_key]))

    return StagingRules(
        small_wait=_wait(CONF_SMALL_WAIT_DAYS),
        medium_wait=_wait(CONF_MEDIUM_WAIT_DAYS),
        big_wait=_wait(CONF_BIG_WAIT_DAYS),
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
    def __init__(self, hass: HomeAssistant, rules: StagingRules, excluded_entities: frozenset[str] = frozenset()) -> None:
        self.hass = hass
        self.rules = rules
        self.excluded_entities = excluded_entities
        # entity_id -> {"entity_id", "version_size", "status", "remaining_seconds", "installable"}
        self.cache: dict[str, dict] = {}
        self._listeners: list[Callable[[], None]] = []
        self._install_listeners: list[InstallListener] = []
        self._unsub_state_changed: Callable[[], None] | None = None
        self._unsub_recheck: Callable[[], None] | None = None
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
            await self._async_refresh_one(entity_id)
            await asyncio.sleep(_STARTUP_QUERY_STAGGER)

    @callback
    def async_stop(self) -> None:
        if self._unsub_state_changed is not None:
            self._unsub_state_changed()
            self._unsub_state_changed = None
        if self._unsub_recheck is not None:
            self._unsub_recheck()
            self._unsub_recheck = None

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
        for entity_id, cached in self.cache.items():
            if cached["status"] == "skipped":
                if not self._is_own_skip(entity_id, cached["latest_version"]):
                    continue
            available_since = dt_util.parse_datetime(cached["available_since"])
            result = evaluate_staging(cached["version_size"], available_since, now, self.rules)
            cached["status"] = result.status
            cached["remaining_seconds"] = (
                round(result.remaining.total_seconds()) if result.remaining is not None else None
            )
            cached["auto_install_excluded"] = _is_excluded_from_auto_install(
                self.hass, entity_id, self.excluded_entities
            )

    @callback
    def _async_periodic_recheck(self, now: datetime) -> None:
        self._recompute_all(now)
        for listener in list(self._listeners):
            listener()

    async def async_update_rules(self, rules: StagingRules, excluded_entities: frozenset[str] | None = None) -> None:
        """Applies newly-saved staging rules (and, since 2026-07-16, the
        user's own excluded-entities picks) without a full entry reload (see
        __init__.py's update_listener): the already-cached installed_version/
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
        self._recompute_all(dt_util.utcnow())
        for listener in list(self._listeners):
            listener()

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

    async def _async_refresh_one(self, entity_id: str) -> None:
        state = self.hass.states.get(entity_id)
        if state is None:
            self.cache.pop(entity_id, None)
            return

        # HA's own update entities are always exactly "on" (an update is
        # available) or "off" -- "off" normally means genuinely up to
        # date, but also covers a *skipped* update (homeassistant/
        # components/update/__init__.py's own state logic: latest_version
        # == skipped_version reports "off" too, confirmed against source).
        if state.state != "on":
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
            self.cache.pop(entity_id, None)
            return
        await self._async_cache_active(entity_id, state, current, latest)

    async def _async_cache_active(self, entity_id: str, state: State, current: str, latest: str) -> None:
        size = classify_version_size(current, latest)
        now = dt_util.utcnow()
        # Uses this entry's actual configured rules (settings panel), not
        # always the hardcoded defaults -- a user may have given "big" a
        # real wait instead of "always blocked" (see FUTURE.md). Only skip
        # the recorder query when the *configured* wait for this size is
        # None, since only then can available_since not change the answer.
        rules = self.rules
        configured_wait = wait_for_size(rules, size)
        if configured_wait is None:
            available_since = now
        else:
            available_since = await _async_available_since(self.hass, entity_id, latest)
        result = evaluate_staging(size, available_since, now, rules)
        # Some update entities (e.g. firmware that must be flashed manually)
        # only ever report that a newer version exists, with no install
        # action at all -- ready/waiting/blocked is still meaningful for
        # "should you move to this version", but install_manager.py's
        # auto-install must gate on this: never call update.install on an
        # entity that doesn't support it.
        installable = bool(state.attributes.get("supported_features", 0) & UpdateEntityFeature.INSTALL)
        self.cache[entity_id] = {
            "entity_id": entity_id,
            "installed_version": current,
            "latest_version": latest,
            "version_size": size,
            "status": result.status,
            "remaining_seconds": (
                round(result.remaining.total_seconds()) if result.remaining is not None else None
            ),
            "installable": installable,
            # Exposed mainly so the recorder lookup above can actually be
            # checked by hand (diagnostics download) instead of only being
            # inferable from status/remaining_seconds.
            "available_since": available_since.isoformat(),
            # Core/Supervisor/HAOS, plus whatever the user picked themselves:
            # always manual, regardless of the size/auto-install settings --
            # install_manager.py checks this before ever auto-installing.
            # Doesn't change size/status here, those stay informational.
            "auto_install_excluded": _is_excluded_from_auto_install(self.hass, entity_id, self.excluded_entities),
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
        }

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
            "remaining_seconds": None,
            "installable": bool(state.attributes.get("supported_features", 0) & UpdateEntityFeature.INSTALL),
            "available_since": available_since,
            "auto_install_excluded": _is_excluded_from_auto_install(self.hass, entity_id, self.excluded_entities),
            # Always False here -- reaching _cache_skipped at all already
            # means the caller's own is_own_skip check said this isn't
            # ours (see _async_refresh_one). See _async_cache_active's own
            # comment for what this field is for.
            "hidden_by_update_manager": False,
        }
