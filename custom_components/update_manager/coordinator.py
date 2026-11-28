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
from typing import Any, cast

from homeassistant.components.update import UpdateEntityFeature
from homeassistant.core import CoreState, Event, HomeAssistant, State, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import EventStateChangedData, async_track_point_in_time, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .announcer import community_blocks_auto_install
from .community_verdict import CommunityVerdictManager
from .const import (
    CONF_EXCLUDED_ENTITIES,
    CONF_LARGE_WAIT_DAYS,
    CONF_MEDIUM_WAIT_DAYS,
    CONF_SMALL_WAIT_DAYS,
    CONF_TRUSTED_VOTERS,
    CONF_WHITELISTED_ENTITIES,
    DEFAULT_WAIT_DAYS,
    DOMAIN,
    WEEKDAY_READY_OPTION_KEYS,
)
from .community_votes_api import async_fetch_authoritative_json
from .device_identity import resolve_zigbee_manufacturer_model_for_entity
from .entity_rename import relabel_key
from .firmware_version_discovery import real_versions_for_entity, same_value_for_different_raw
from .firmware_version_registry import FirmwareVersionManager
from .firmware_version_submit import async_has_pending_submission, async_submit_firmware_version
from .github_auth import GitHubAuthManager
from .github_release_notes import parse_release_url
from .postponement_schedule import DayRule, EMPTY_SCHEDULE, PostponementSchedule, next_allowed_ready
from .zigbee import slugify_zigbee_model
from .zigbee_ota_release_notes import parse_zigbee_ota_version
from .semver import Size, classify_version_size, size_rank, strip_version_prefix
from .staging import StagingRules, StagingResult, evaluate_staging, wait_for_size
from .vendor_fallback_urls import release_url_for_entity

_LOGGER = logging.getLogger(__name__)

_AVAILABLE_SINCE_STORAGE_VERSION = 1
_AVAILABLE_SINCE_STORAGE_KEY = f"{DOMAIN}_available_since"

_LAST_INSTALLED_STORAGE_VERSION = 1
_LAST_INSTALLED_STORAGE_KEY = f"{DOMAIN}_last_installed_version"

_FORCE_READY_STORAGE_VERSION = 1
_FORCE_READY_STORAGE_KEY = f"{DOMAIN}_force_ready"

# One-shot wait after an install completes, before checking whether its
# device's own sw_version has caught up -- a Zigbee2MQTT-managed device
# typically only reports its freshly-installed firmware's real version
# once Z2M has re-interviewed it, which isn't guaranteed to have happened
# in the same instant installed_version itself changes. Bounded, not a
# retry loop: missing this window just means this one occurrence goes
# unlearned, the same as today's status quo before this feature existed.
_FIRMWARE_SUBMISSION_INTERVIEW_GRACE = timedelta(seconds=30)

# How far back "recently installed" reaches for the firmware-version
# submission retry, both the manual refresh click (websocket_api.py's own
# _handle_refresh_community_verdicts, which imports this same constant)
# and _async_periodic_recheck's own automatic sweep below. Matches
# History's own "This week" bucket (update-manager-panel.js's own
# historySections), not an arbitrary new window of its own. Found live,
# 2026-11-25: unscoped, a manual refresh submitted three completely
# unrelated devices at once, each installed weeks earlier, purely because
# nothing had ever checked them before.
FIRMWARE_SUBMISSION_RECENT_INSTALL_WINDOW = timedelta(days=7)

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

# How long after this coordinator's own async_start a contradiction against
# self._last_installed_version's own persisted, pre-restart baseline is
# trusted less than that baseline itself. See _within_startup_grace's own
# docstring for the full reasoning and its two call sites.
_RESTART_LAG_GRACE = timedelta(minutes=10)

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


def has_native_auto_update(state: State) -> bool:
    """True when Home Assistant's own per-entity "Auto update" toggle is on
    for this entity (state.attributes["auto_update"]), not anything Update
    Manager itself set. Home Assistant then installs this update on its own
    schedule regardless of staging/community/auto-install rules here, and
    its own update.skip service refuses to run on it (see staging_skip.py's
    own auto_update check). install_manager.py treats this the same as
    auto_install_excluded, and the panel badges it, for that same reason."""
    return bool(state.attributes.get("auto_update"))


def _is_whitelisted_for_auto_install(entity_id: str, whitelisted_entities: frozenset[str]) -> bool:
    """The opposite standing override -- see CONF_WHITELISTED_ENTITIES's
    own comment. An entity can never be in both this and excluded_entities
    at once (websocket_api.py's own async_apply_options rejects that
    combination outright), so there's no precedence question to resolve
    between the two of these at the call site either."""
    return entity_id in whitelisted_entities


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


def _version_size_real(installed_version_real: str | None, latest_version_real: str | None) -> Size | None:
    """classify_version_size applied to the real, human-readable firmware
    strings instead of the raw OTA integers, whenever both sides are known
    -- shared by _async_cache_active and
    _async_refresh_firmware_version_display (found by /code-review: both
    had their own copy of this exact expression)."""
    if installed_version_real and latest_version_real:
        return classify_version_size(installed_version_real, latest_version_real)
    return None


def excluded_entities_from_options(options: dict) -> frozenset[str]:
    return frozenset(options.get(CONF_EXCLUDED_ENTITIES, []))


def whitelisted_entities_from_options(options: dict) -> frozenset[str]:
    return frozenset(options.get(CONF_WHITELISTED_ENTITIES, []))


def trusted_voters_from_options(options: dict) -> list[str]:
    return list(options.get(CONF_TRUSTED_VOTERS, []))


def _migrate_entity_id_keys_to_unique_id(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """One-time upgrade for data persisted before _available_since/
    _last_installed_version/_force_ready switched from entity_id keys to
    unique_id keys (see UpdateManagerCoordinator._stable_key's own
    docstring for why -- found live, 2026-08-19: a renamed entity's
    available_since silently reset to "now" despite async_rename_entity's
    own careful relabeling, a race this re-keying removes outright rather
    than trying to out-synchronize). Only re-keys an entry whose key still
    looks like an entity_id (starts with "update.") -- an already-migrated,
    unique_id-keyed entry is left alone, so this is safe to run
    unconditionally on every load, not a true one-shot. An entity that no
    longer exists at all has no stable key left to migrate to and is
    dropped -- a stale record for a gone entity has no use anyway."""
    registry = er.async_get(hass)
    migrated: dict[str, Any] = {}
    for key, value in data.items():
        if key.startswith("update."):
            entry = registry.async_get(key)
            if entry is None or not entry.unique_id:
                continue
            migrated[entry.unique_id] = value
        else:
            migrated[key] = value
    return migrated

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

InstallListener = Callable[[str, str, str, State, bool], None]


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

    # WEEKDAY_READY_OPTION_KEYS is a real, fixed 7-entry constant
    # (Monday..Sunday, see its own comment in const.py), just not declared
    # as a fixed-length tuple type there. The cast preserves
    # PostponementSchedule.days' own stronger, self-documenting length-7
    # type instead of weakening it to match.
    days = tuple(_day(enabled_key, time_key) for enabled_key, time_key in WEEKDAY_READY_OPTION_KEYS)
    return PostponementSchedule(days=cast("tuple[DayRule, DayRule, DayRule, DayRule, DayRule, DayRule, DayRule]", days))


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
        whitelisted_entities: frozenset[str] = frozenset(),
        firmware_version_manager: FirmwareVersionManager | None = None,
        github_auth_manager: GitHubAuthManager | None = None,
        recent_install_entity_ids_provider: Callable[[], set[str]] | None = None,
    ) -> None:
        self.hass = hass
        self.rules = rules
        self.excluded_entities = excluded_entities
        self.whitelisted_entities = whitelisted_entities
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
        # Same None-able reasoning as _community_verdict_manager just above.
        # github_auth_manager is only ever read (never written) here, to get
        # a valid access token for a firmware-version submission -- the
        # manager instance itself is owned/constructed by __init__.py, same
        # as the other two.
        self._firmware_version_manager = firmware_version_manager
        self._github_auth_manager = github_auth_manager
        # __init__.py's own closure over install_log.py's own
        # entity_ids_installed_since, a plain callable, not a direct
        # InstallLog reference, so this module never needs to know that
        # type exists at all. Read by _async_periodic_recheck's own
        # firmware-submission retry below; None-able the same way every
        # other optional manager reference here is, for a future test.
        self._recent_install_entity_ids_provider = recent_install_entity_ids_provider
        # Only wireable once install_manager exists, same reverse-direction
        # reasoning as rollout_manager.py's own set_recently_executed_setter
        # (avoids an import cycle): set via set_retry_failed_ai_checks below,
        # from __init__.py, right after InstallManager is constructed.
        self._retry_failed_ai_checks: Callable[[], None] | None = None
        # Serializes every firmware-version submission this instance ever
        # attempts (see async_check_firmware_version_submission's own
        # comment for the cross-key, same-remote-file race this closes) --
        # submissions are rare, so full serialization costs nothing.
        self._firmware_submission_lock = asyncio.Lock()
        # Set once via set_integration_version, right after __init__.py
        # fetches the manifest.json version -- not known at construction
        # time itself, same reasoning as coordinator.set_master_enabled
        # being a post-construction setter rather than a constructor arg.
        self._integration_version: str | None = None
        # entity_id -> {"entity_id", "version_size", "status", "remaining_seconds", "ready_at", "ready_since", "installable"}
        self.cache: dict[str, dict] = {}
        # entity_id -> {"version", "since", "max_size"}: the authoritative
        # "when did an update of this size or smaller first become
        # available since the last real install" record, see
        # _async_get_available_since. Persisted (unlike self.cache, which is
        # rebuilt from scratch on every restart) precisely because it must
        # survive a restart intact: direct user feedback, the recorder-only
        # lookup this replaces could quietly reset an update's wait back to
        # "just now" after a restart, the entity briefly going unavailable,
        # or an integration reload, none of which mean the update actually
        # just became available again.
        #
        # max_size (added for issue #17) is this record's own anchor: as
        # long as a newly available version's size never exceeds it, this
        # same "since" keeps applying, however many times the exact target
        # version itself changes -- only a genuinely bigger jump than
        # anything seen since the last install resets "since" to right now
        # (and max_size to match), since that's a new risk that deserves
        # its own full consideration time, not an inherited, nearly-spent
        # one. Missing (an older persisted record, or
        # async_reset_available_since's own deliberate re-anchor) is
        # treated the same as "trust this anchor once more, and start
        # tracking max_size as of whatever size is checked next" -- never a
        # reason to reset on its own.
        self._available_since: dict[str, dict[str, str]] = {}
        self._available_since_store: Store[dict[str, dict[str, str]]] = Store(
            hass, _AVAILABLE_SINCE_STORAGE_VERSION, _AVAILABLE_SINCE_STORAGE_KEY
        )
        # entity_id -> this entity's own installed_version, as of the last
        # time we saw it (any refresh, not just an install) -- persisted
        # (unlike self.cache) precisely so a restart has something to
        # compare the live post-restart value against, see
        # _check_and_advance_installed_baseline. Installing HA Core
        # itself (and likely Supervisor/OS) always requires a full HA
        # restart, so the before/after installed_version transition happens
        # *across* that restart boundary -- _handle_state_changed only ever
        # compares a live event's own old_state/new_state, and a freshly-
        # starting process's first-ever state report for any entity has no
        # old_state
        # at all, so that listener structurally can never see this specific
        # transition. Found live, 2026-07-27: HA Core updates never
        # appeared on the History page at all.
        self._last_installed_version: dict[str, str] = {}
        self._last_installed_store: Store[dict[str, str]] = Store(
            hass, _LAST_INSTALLED_STORAGE_VERSION, _LAST_INSTALLED_STORAGE_KEY
        )
        # Set once, at the top of async_start; see _within_startup_grace's
        # own docstring for what this gates. In-memory only, deliberately
        # never persisted: it means "since this specific process started",
        # which is by definition a fresh fact every time this coordinator is
        # constructed, nothing a restart could ever need to remember.
        self._started_at: datetime | None = None
        # entity_id -> {"version", "at"}: the exact latest_version the
        # panel's own "Ready now" button forced ready for, overriding the
        # normal wait-days countdown for that one jump -- lets someone skip
        # the rest of a postponement period they've decided isn't needed
        # for this specific update. "at" (added alongside "version" -- was
        # a bare version string before) is the real click instant, the only
        # source for this specific jump's own "ready since" fact once
        # forced (see _resolve_ready_since's own docstring); a record
        # loaded from before this field existed has no "at" of its own
        # (see async_start's own migration), which _resolve_ready_since
        # already treats as a genuine, honest gap rather than a guess.
        # Self-clears the moment latest_version
        # moves past the forced version: only ever consulted when it still
        # matches the entity's *current* latest (see _async_cache_active/
        # _recompute_all), so a version bump silently orphans the old
        # record, no explicit cleanup needed here, same reasoning
        # staging_skip.py's own self._skipped already relies on for itself.
        self._force_ready: dict[str, dict[str, str]] = {}
        self._force_ready_store: Store[dict[str, Any]] = Store(
            hass, _FORCE_READY_STORAGE_VERSION, _FORCE_READY_STORAGE_KEY
        )
        # (owner, repo, tag) -> GitHub's own real "prerelease" flag, gained
        # for free whenever websocket_api.py's own
        # async_fetch_github_release_notes already fetches a repo's full
        # releases list for an unrelated reason (release notes), never a
        # fetch of its own; see remember_release_prerelease. Session-lived
        # only, no Store: losing this on restart costs nothing, it only
        # ever sharpens classify_version_size's own otherwise-numeric-only
        # size classification (semver.py's own known_prerelease parameter)
        # whenever this happens to already be in hand.
        self._known_prereleases: dict[tuple[str, str, str], bool] = {}
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
        # Same wiring pattern as self._is_own_skip above, same reason
        # (install_manager.py depends on this coordinator, not the other
        # way around, so its own self._postponed can't be read directly
        # here). Lets _derive_status_fields report "waiting" for an
        # entity install_manager.py has parked in self._postponed, so
        # every consumer of cached["status"] (sensor.py's own per-status
        # counts, staging_skip.py's own hide_postponed eligibility check,
        # not just the panel's own separate, frontend-only reclassification)
        # agrees with each other. Found live, 2026-11-02: a postponed
        # entity counted under the "Ready" sensor while the panel showed it
        # under "Postponed", and hide_postponed didn't hide it from HA's
        # own update count the way a staging-wait "Postponed" entity
        # already does, because this coordinator had no way to know a
        # "ready" entity was actually blocked at the real install-attempt
        # level. Defaults to "never postponed" so this coordinator still
        # works standalone without that wiring.
        self._is_postponed: Callable[[str], bool] = lambda entity_id: False

    def set_master_enabled(self, enabled: bool) -> None:
        self.master_enabled = enabled

    def set_integration_version(self, version: str) -> None:
        """Read by the firmware-version submission body (its own "Reported
        by Update Manager version" provenance field) -- see __init__.py's
        own call site for why this is a post-construction setter rather
        than a constructor arg."""
        self._integration_version = version

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

    def set_postponed_checker(self, checker: Callable[[str], bool]) -> None:
        self._is_postponed = checker

    async def async_start(self) -> None:
        # Gathered, not sequential awaits -- fully independent Store reads,
        # found by code review, 2026-07-27.
        available_since, last_installed_version, force_ready = await asyncio.gather(
            self._available_since_store.async_load(),
            self._last_installed_store.async_load(),
            self._force_ready_store.async_load(),
        )
        self._available_since = _migrate_entity_id_keys_to_unique_id(self.hass, available_since or {})
        self._last_installed_version = _migrate_entity_id_keys_to_unique_id(self.hass, last_installed_version or {})
        # Only armed for a genuine Home Assistant restart, not an integration
        # reload while HA itself was already running (hass.state is only
        # ever CoreState.starting/not_running for a config entry's own
        # async_start during real startup, already CoreState.running for a
        # later reload triggered on a live instance). Found live, 2026-08-25:
        # left unconditional, a reload during active development/testing
        # re-armed this same 10-minute window on every single reload, and a
        # real ESPHome install completed in that window went completely
        # unlogged (see _check_and_advance_installed_baseline's own early
        # return below), not merely misattributed like the restart-lag
        # case this was actually built for.
        self._started_at = dt_util.utcnow() if self.hass.state != CoreState.running else None
        # Pre-{"version", "at"} records on disk are a bare version string
        # (this field's own shape before it gained "at") -- migrated in
        # place to the current shape, "at" left absent rather than guessed.
        self._force_ready = _migrate_entity_id_keys_to_unique_id(
            self.hass,
            {
                entity_id: ({"version": record} if isinstance(record, str) else record)
                for entity_id, record in (force_ready or {}).items()
            },
        )

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
            state = self.hass.states.get(entity_id)
            baseline_already_checked = False
            if state is not None:
                baseline_already_checked = self._check_and_advance_installed_baseline(
                    entity_id, state, retroactive=True
                )
            await self._async_refresh_one(
                entity_id, baseline_already_checked=baseline_already_checked, retroactive=True
            )
            await asyncio.sleep(_STARTUP_QUERY_STAGGER)

        # _async_refresh_one above (unlike its own async_refresh_one/
        # _async_handle_changed wrappers) doesn't call _fire_listeners on
        # its own -- without this, _schedule_next_wakeup's own precise
        # wake-up wouldn't actually start covering anything until the first
        # periodic recheck, a real state_changed event, or a settings save
        # happened to fire it, up to _RECHECK_INTERVAL after a fresh
        # restart.
        self._fire_listeners()

    def _stable_key(self, entity_id: str) -> str:
        """The key self._available_since/self._last_installed_version/
        self._force_ready are actually stored under: an entity's own
        unique_id when the entity registry has one, entity_id itself as a
        fallback for the rare entity with no registry entry at all.
        unique_id survives an entity_id rename, entity_id doesn't -- found
        live, 2026-08-19: a renamed entity's available_since silently
        reset to "now" despite async_rename_entity's own careful
        relabeling of these dicts, because the entity's own independent,
        live refresh for its brand-new entity_id could race that relabel
        and win (a slower recorder-based "first time seen" lookup finding
        nothing yet for a key that's seconds old, then overwriting the
        correctly-relabeled value once it finally resolves). Keying by
        unique_id removes the relabeling -- and therefore the race -- for
        these three structures entirely: the key never changes, so there's
        nothing left to relabel. self.cache stays entity_id-keyed (see
        async_rename_entity below); it has no such "trust what's cached,
        only recompute if missing" pattern (see _async_cache_active, which
        unconditionally overwrites it on every refresh), so it self-heals
        on the next refresh regardless, and it's read directly by entity_id
        from several other files, too wide a blast radius to re-key for a
        bug that structure was never actually at risk of."""
        entry = er.async_get(self.hass).async_get(entity_id)
        return entry.unique_id if entry is not None and entry.unique_id else entity_id

    @callback
    def _check_and_advance_installed_baseline(self, entity_id: str, state: State, *, retroactive: bool) -> bool:
        """Compares `state`'s own installed_version against the persisted
        restart-recovery baseline (self._last_installed_version), fires the
        install listeners if they genuinely disagree, then advances the
        baseline to match -- in that order, so the comparison always sees
        the *previous* baseline, never one this same call already
        overwrote. Three callers, all needing exactly this: async_start's
        own startup sweep (an install that completed entirely while HA was
        down), _async_refresh_one (the live event/on-demand-refresh path),
        and _async_periodic_recheck (a self-healing safety net, catching
        anything the other two ever miss -- a dropped/coalesced event, or
        some future integration's own bogus-placeholder quirk, added
        2026-08-18 after finding _handle_state_changed's own live-path
        comparison had never gotten the same placeholder protection this
        one always had).

        Both a falsy value and _PLACEHOLDER_INSTALLED_VERSION are excluded
        from *both* sides of the comparison and from ever being written as
        the new baseline (see that constant's own comment for the confirmed
        Zigbee2MQTT restart quirk, and an empty-string ESPHome one found
        live 2026-08-18: a Home Assistant Voice PE briefly reporting no
        installed_version at all while genuinely unavailable) -- a bogus
        placeholder must never look like a real "from" version, and must
        never poison the baseline for next time either.

        `retroactive` (required, no default -- every caller must decide
        deliberately) is False only for _async_refresh_one's own call: that
        path always runs moments after something happening right now (a
        live state_changed event, or an explicit on-demand refresh), so
        `state`'s own context is still the genuine, trustworthy one for
        whatever just happened. True for the startup sweep and periodic
        recheck: both read whatever the *current* state happens to be, at a
        moment with no guaranteed relationship to when the transition being
        detected actually occurred (possibly across a restart) -- found by
        code review, 2026-08-18: __init__.py's own _on_install used to
        trust state.context.user_id for its "manual" vs "external"
        classification regardless of which path fired it, misclassifying a
        genuinely manual install as "external" whenever it was only
        detected this retroactive way (context.user_id reads as empty on a
        state that's been sitting since before/across a restart, same as a
        real external update would). For a fresh restart specifically,
        coordinator.cache is always empty for this entity_id at this point
        (rebuilt from scratch every restart, no entry yet), so the
        listener's own available_since naturally comes back None -- an
        honest "we don't know", not a guess, since HA genuinely wasn't
        running to observe when this update actually became available.

        Previously a known limitation (found by code review, 2026-07-27):
        for the same restart reason, __init__.py's own _on_install used to
        always log this as a manual install, never an auto-install, even
        if install_manager.py's own InstallManager actually dispatched it
        right before the restart. was_auto_installed() reads
        InstallManager._recently_executed, an in-memory-only dict that
        can't survive a restart any more than this coordinator's own
        un-persisted cache can. Resolved 2026-11-09 not by persisting
        dispatch records across a restart (the real fix that gap's own
        note called for, genuinely invasive), but by the same "don't
        assert what isn't known" principle applied to install_method
        generally that same day: retroactive now routes straight to
        "external" below, the same bucket that already means "not
        confirmed", shown as nothing at all rather than the wrong, too-
        confident "manual" it used to default to.

        Returns whether this call actually evaluated the transition
        (fired the install listeners, or found no disagreement worth
        acting on) rather than being suppressed outright by the startup
        grace window below. async_start's own startup sweep uses this to
        decide whether _async_refresh_one's own follow-up call for the
        same entity_id is still needed: found live, 2026-09-12, a real
        Core update installed via a restart went missing from History
        entirely, not just misattributed. The sweep's own retroactive call
        is always inside the grace window right at process start (it was
        just armed a moment earlier in this same async_start), so it's
        suppressed every single time for a transition discovered this way;
        skipping the follow-up unconditionally, as a prior fix here did,
        left nothing to ever actually log it.

        Home Assistant's own Core/Supervisor/OS update entities are exempt
        from the grace window below entirely, see that condition's own
        comment for why (2026-11-02)."""
        new_installed = state.attributes.get("installed_version")
        if not new_installed or new_installed == _PLACEHOLDER_INSTALLED_VERSION:
            return True
        key = self._stable_key(entity_id)
        old_installed = self._last_installed_version.get(key)
        if old_installed and old_installed != _PLACEHOLDER_INSTALLED_VERSION and old_installed != new_installed:
            if (
                retroactive
                and self._within_startup_grace()
                and home_assistant_component_for_entity(self.hass, entity_id) is None
            ):
                # Contradicts a baseline persisted from before this
                # process's own current run. See _within_startup_grace's
                # own docstring and _RESTART_LAG_GRACE's own comment. Trust
                # that persisted baseline instead, this soon after starting:
                # neither log a backwards install for this, nor let it
                # clobber the baseline. Once this window has passed, every
                # contradiction is trusted again exactly as before.
                #
                # Only for a retroactive read (the startup sweep/periodic
                # recheck this was actually built for), never for a live,
                # real-time state_changed event. Found live, 2026-08-25: a
                # genuinely installed update, detected live moments after a
                # restart (unavoidable when testing this integration itself,
                # since a Python change requires a full restart to take
                # effect, immediately followed by testing it), was still
                # being swallowed here even though it was never in question.
                # A live event is, by definition, a real observation right
                # now, not something to second-guess the way a retroactive
                # snapshot with no reliable timestamp has to be.
                #
                # Home Assistant's own Core/Supervisor/OS update entities
                # (found live, 2026-11-02: a Core update went undetected for
                # a full week) are exempted from this suppression entirely:
                # unlike a HACS-managed integration that can take a moment
                # to rescan and report its true state after restarting, all
                # three read their installed_version synchronously at setup
                # (homeassistant.const.__version__ for Core, a direct
                # Supervisor/OS API call for the other two), so there's
                # nothing here for the grace window to actually guard
                # against. Suppressing them anyway was actively harmful:
                # once installed, all three immediately stop being a
                # pending update and drop out of self.cache, so
                # _async_periodic_recheck's own self-healing loop (which
                # only ever walks self.cache) can never reach them again:
                # the only thing left to catch a suppressed transition here
                # was pure chance, whichever future restart happened to
                # observe it outside its own new grace window. Safe to
                # evaluate immediately instead: _on_install's own retroactive
                # branch already always resolves to "manual" for these
                # three regardless (see this method's own docstring,
                # "Core/Supervisor/OS themselves are hard-excluded from
                # auto-install entirely"), so there's no misattribution risk
                # being skipped here either.
                return False
            self._fire_install_listeners(entity_id, old_installed, new_installed, state, retroactive)
        if old_installed != new_installed:
            self._last_installed_version[key] = new_installed
            self._last_installed_store.async_delay_save(lambda: self._last_installed_version, 1.0)
        return True

    def _within_startup_grace(self) -> bool:
        """True for a short window after this coordinator's own async_start.
        Some update-providing integrations (a HACS-managed custom
        integration, for one) can take a moment after a restart to rescan
        and report their own true state, briefly contradicting self.
        _last_installed_version's own pre-restart record; this method's two
        call sites both trust that persisted record a little longer here
        instead. Tied to process start rather than to when the baseline was
        last confirmed, since the latter would re-arm on every single
        install and could suppress a second, genuinely independent one
        minutes later.

        _check_and_advance_installed_baseline's own call site only consults
        this for a retroactive read (the startup sweep/periodic recheck this
        was actually built for), never for a live, real-time state_changed
        event. Found live, 2026-08-25: a genuinely installed update,
        detected live moments after a restart, was still being swallowed
        from History entirely here, not just misattributed, even though a
        live event is a real observation right now with nothing to
        second-guess. That scenario is common, not rare, precisely when
        developing this integration itself: a Python change needs a full
        restart to take effect, and the natural next step is testing it
        immediately, almost always inside this same window.
        _async_refresh_one's own call site (the panel's own "needs update"
        display, not History) has no such distinction to make and keeps
        trusting this for both kinds of read, since its own condition is
        already narrow (the entity's own latest_version must exactly match
        something this instance already confirmed installed) and only
        delays a display update briefly rather than dropping a fact
        outright.

        Known limitation: a fixed window, not a wait for the actual rescan
        to finish, so an unusually slow restart could still exit this
        window before that rescan catches up."""
        return self._started_at is not None and dt_util.utcnow() - self._started_at < _RESTART_LAG_GRACE

    def _fire_install_listeners(
        self, entity_id: str, old_installed: str, new_installed: str, state: State, retroactive: bool
    ) -> None:
        """The one place every install listener actually gets called, shared
        by the live path (_handle_state_changed) and the shared
        _check_and_advance_installed_baseline above -- found by review,
        these previously each had their own identical `for listener in
        list(self._install_listeners): listener(...)` loop."""
        for listener in list(self._install_listeners):
            listener(entity_id, old_installed, new_installed, state, retroactive)

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
        # One hass.states.get per entity_id, not two (the staleness check
        # below and native_auto_update further down used to each fetch it
        # separately) -- this runs every recompute pass over every cached
        # entity, a real hot path.
        states = {entity_id: self.hass.states.get(entity_id) for entity_id in self.cache}
        stale = [
            entity_id
            for entity_id, state in states.items()
            if state is not None
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
            cached["auto_install_whitelisted"] = _is_whitelisted_for_auto_install(
                entity_id, self.whitelisted_entities
            )
            state = states[entity_id]
            if state is not None:
                cached["native_auto_update"] = has_native_auto_update(state)

    async def async_prune_removed_entities(self) -> None:
        """An entity genuinely gone (its own integration/app removed) used
        to rely entirely on _handle_state_changed's own live event to
        notice and clean up self.cache (install_manager.py's own
        _pending/_postponed entries following along via its own next
        tick, see _async_evaluate_one's own cached-is-None handling). If
        that one event was ever missed, nothing else ever asked again,
        found live, 2026-11-28 (issue #20): a removed app's own entity
        kept showing "Postponed" on the Updates tab indefinitely.

        Shared by _async_periodic_recheck's own self-healing sweep below
        and the manual refresh button (websocket_api.py's own
        refresh_community_verdicts handler), same "a manual refresh
        should also retry what's stale" intent every other call that
        handler already makes has. _async_refresh_one's own None-state
        branch is exactly the cleanup needed here, reused directly rather
        than a second copy of it."""
        for entity_id in list(self.cache):
            if self.hass.states.get(entity_id) is None:
                await self._async_refresh_one(entity_id)

    async def _async_periodic_recheck(self, now: datetime) -> None:
        # Self-healing safety net (added 2026-08-18): re-derives the
        # restart-recovery baseline from live state for every currently-
        # tracked entity, not just once at startup or reactively on a live
        # state_changed event -- catches anything those two ever miss (a
        # dropped/coalesced event, some future integration's own bogus-
        # placeholder quirk not yet seen). Cheap (an in-memory state read
        # + dict compare per entity, no recorder queries), staggered the
        # same modest amount async_start's own startup sweep already uses
        # to stay gentle on a large instance, even though this now repeats
        # every _RECHECK_INTERVAL rather than running once.
        await self.async_prune_removed_entities()
        for entity_id in list(self.cache):
            state = self.hass.states.get(entity_id)
            if state is not None:
                self._check_and_advance_installed_baseline(entity_id, state, retroactive=True)
            await asyncio.sleep(_STARTUP_QUERY_STAGGER)
        self._recompute_all(now)
        self._fire_listeners()
        # Firmware-version submission's own self-healing retry, direct user
        # feedback, 2026-11-25: the install-completion listener's own
        # one-shot grace window (_FIRMWARE_SUBMISSION_INTERVIEW_GRACE) can
        # miss a device that hasn't re-interviewed yet, and the manual
        # refresh button is the only other thing that ever retries it,
        # easy to simply never get around to clicking. This piggybacks on
        # the exact same self-healing spirit this method already has for
        # the installed-baseline recompute above, scoped the identical
        # "recent installs only" way the manual refresh button is (see
        # FIRMWARE_SUBMISSION_RECENT_INSTALL_WINDOW's own comment for why
        # that scope matters at all), not awaited inline: a slow GitHub
        # round trip has no reason to hold up this recheck's own, more
        # time-sensitive work above.
        if self._recent_install_entity_ids_provider is not None:
            self.hass.async_create_task(self._async_retry_recent_firmware_submissions())
        # Same self-healing spirit, direct user feedback, 2026-11-27: an
        # entity whose AI safety check never ran at all (not a genuine
        # failure, see install_manager.py's own async_retry_missing_ai_checks
        # docstring for why only this narrower case belongs on a timer,
        # not every past failure too) could otherwise sit unchecked
        # forever if nobody happens to click the manual refresh button.
        # That method already schedules its own detached tasks and
        # returns immediately, nothing to await here either.
        if self._retry_failed_ai_checks is not None:
            self._retry_failed_ai_checks()

    def set_retry_failed_ai_checks(self, callback: Callable[[], None]) -> None:
        """See self._retry_failed_ai_checks's own comment for why this is a
        post-construction setter rather than a constructor argument."""
        self._retry_failed_ai_checks = callback

    async def _async_retry_recent_firmware_submissions(self) -> None:
        """See _async_periodic_recheck's own call site for why this exists.
        A plain per-entity loop, not async_force_refresh_firmware_versions
        (which also force-refreshes display data for literally every
        update entity, the right cost for a single manual click, not for
        something that now also runs every _RECHECK_INTERVAL on its own)."""
        if self._firmware_version_manager is None or self._recent_install_entity_ids_provider is None:
            return
        recent_entity_ids = self._recent_install_entity_ids_provider()
        if not recent_entity_ids:
            return
        await asyncio.gather(
            *(
                self.async_check_firmware_version_submission_for_current_install(entity_id)
                for entity_id in recent_entity_ids
            )
        )

    async def async_update_rules(
        self,
        rules: StagingRules,
        excluded_entities: frozenset[str] | None = None,
        schedule: PostponementSchedule | None = None,
        whitelisted_entities: frozenset[str] | None = None,
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
        if whitelisted_entities is not None:
            self.whitelisted_entities = whitelisted_entities
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
        # No compare-and-fire here anymore (found live, 2026-08-18, right
        # after adding it back below): this used to duplicate every real
        # install into two identical History entries a couple milliseconds
        # apart, one from here and one from _check_and_advance_installed_
        # baseline (via _async_refresh_one, scheduled a few lines down and
        # *always* reached whenever installed_version actually changed --
        # see old_key/new_key below, they can never compare equal in that
        # case). That shared helper already has the exact same falsy/
        # placeholder guard this block used to have inline (see its own
        # docstring), so it alone is enough; this function's only job now
        # is deciding whether anything worth a fresh recompute happened at
        # all.
        old_latest = old_state.attributes.get("latest_version") if old_state else None
        new_latest = new_state.attributes.get("latest_version") if new_state else None
        # auto_update included here too, found live, 2026-11-03: toggling
        # Home Assistant's own per-entity "Auto update" switch (Settings >
        # Apps > the app > Info) changes nothing else in this key, so a
        # live flip of just that one attribute used to compare equal and
        # get skipped entirely, leaving cached["native_auto_update"] (see
        # has_native_auto_update) stale until the next unrelated event or
        # the periodic recheck caught up to it.
        old_auto_update = has_native_auto_update(old_state) if old_state else None
        new_auto_update = has_native_auto_update(new_state) if new_state else None
        old_key = (old_state.state, old_installed, old_latest, old_auto_update) if old_state else None
        new_key = (new_state.state, new_installed, new_latest, new_auto_update) if new_state else None
        if old_state is not None and new_state is not None and old_key == new_key:
            # Some other attribute changed (e.g. in_progress toggling
            # during an install) -- not something a fresh recorder lookup
            # would answer differently, skip it rather than re-querying.
            return

        # An entity's very first state this session (old_state is None),
        # seen within the startup grace window, is almost certainly the
        # startup sweep's own blind spot, not a genuinely live transition --
        # confirmed live, 2026-10-20 (direct user feedback, a Core update
        # "not always" making it into History): async_start's own sweep
        # only iterates hass.states.async_entity_ids("update") as it exists
        # at that one instant; an update entity the built-in `update`
        # platform hasn't registered yet at that exact moment (setup order
        # isn't guaranteed relative to this integration's own
        # coordinator.async_start) is simply absent from that snapshot,
        # with nothing to catch it until its own first live state_changed
        # event fires here instead. That event used to always flow through
        # as retroactive=False (the default, correct for a *genuinely* live
        # change on an entity already being tracked), landing in
        # __init__.py's own _on_install with no was_manually_requested/
        # context.user_id left to go on (both wiped by the same restart),
        # falling through to the same unsafe "External" guess the startup
        # sweep's own follow-up call was already fixed for (2026-10-09) --
        # this is the third, until-now-unpatched entry point into the same
        # underlying gap, not a new one. Outside the grace window, or for
        # an entity genuinely new (never tracked before, so no persisted
        # baseline to even compare against), this is False exactly like
        # before, so a real plain reload (2026-08-25's own fix: _started_at
        # is only armed for a genuine restart to begin with) is unaffected.
        retroactive = old_state is None and self._within_startup_grace()
        self.hass.async_create_task(self._async_handle_changed(entity_id, retroactive=retroactive))

    async def _async_handle_changed(self, entity_id: str, *, retroactive: bool = False) -> None:
        await self._async_refresh_one(entity_id, retroactive=retroactive)
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
        self._force_ready[self._stable_key(entity_id)] = {"version": to_version, "at": dt_util.utcnow().isoformat()}
        await self._force_ready_store.async_save(self._force_ready)
        await self.async_refresh_one(entity_id)

    def remember_release_prerelease(self, owner: str, repo: str, tag_name: str, prerelease: bool) -> None:
        """Called by websocket_api.py's own async_fetch_github_release_notes
        as a side effect of a fetch it's already making for an unrelated
        reason (release notes), never triggers one of its own. See
        self._known_prereleases's own comment for why this is worth
        remembering at all."""
        if not tag_name:
            return
        self._known_prereleases[(owner, repo, strip_version_prefix(tag_name))] = prerelease

    def _known_prerelease(self, release_url: str | None, version: str) -> bool:
        """classify_version_size's own known_prerelease argument, from
        whatever remember_release_prerelease has happened to learn so far
        for this exact (repo, version). False (not "unknown", there's no
        third state here) whenever release_url doesn't parse or nothing's
        been learned about this version yet."""
        parsed = parse_release_url(release_url)
        if parsed is None:
            return False
        owner, repo, _ = parsed
        return self._known_prereleases.get((owner, repo, strip_version_prefix(version)), False)

    async def async_rename_entity(self, old_entity_id: str, new_entity_id: str) -> None:
        """Relabels self.cache after a live HA entity registry rename --
        see __init__.py's own EVENT_ENTITY_REGISTRY_UPDATED listener.
        self._available_since/_last_installed_version/_force_ready need no
        relabeling at all anymore (see _stable_key's own docstring): they're
        keyed by unique_id, which a rename never changes. self.cache stays
        entity_id-keyed, relabeled directly here (rather than relying
        solely on the async_refresh_one call below) so it's correct
        immediately even if the entity's live state under the new
        entity_id hasn't caught up yet at the exact instant this fires."""
        cache_entry = relabel_key(self.cache, old_entity_id, new_entity_id)
        if cache_entry is not None:
            cache_entry["entity_id"] = new_entity_id

        # Only refresh if the new entity_id's state is already live --
        # found by code review, 2026-08-18: _async_refresh_one's own
        # None-state branch pops (and persists the deletion of) everything
        # just relabeled above the moment hass.states.get(new_entity_id) is
        # still None, which can genuinely happen if this event fires before
        # the entity's live state has republished under its new id. Safe to
        # skip entirely here -- a later real state_changed event (or the
        # periodic recheck) picks it up correctly once the state exists.
        if self.hass.states.get(new_entity_id) is not None:
            await self.async_refresh_one(new_entity_id)

    async def _async_refresh_one(
        self, entity_id: str, *, baseline_already_checked: bool = False, retroactive: bool = False
    ) -> None:
        state = self.hass.states.get(entity_id)
        if state is None:
            self.cache.pop(entity_id, None)
            # _stable_key's own registry lookup usually can't resolve
            # entity_id here anymore -- for a rename, the registry already
            # only knows the *new* entity_id (so this correctly no-ops,
            # nothing under the old entity_id string to pop from a dict
            # that's keyed by unique_id); for a genuine removal, the
            # registry entry is often gone too by this point, same no-op.
            # A removed entity's own record can end up orphaned here as a
            # result (never popped, since there's no way left to resolve
            # its unique_id) -- accepted as a minor, low-severity tradeoff,
            # not the bug this re-keying exists to fix.
            key = self._stable_key(entity_id)
            if self._available_since.pop(key, None) is not None:
                await self._available_since_store.async_save(self._available_since)
            if self._last_installed_version.pop(key, None) is not None:
                self._last_installed_store.async_delay_save(lambda: self._last_installed_version, 1.0)
            if self._force_ready.pop(key, None) is not None:
                await self._force_ready_store.async_save(self._force_ready)
            return

        # Restart-recovery baseline advance + self-healing install
        # detection, regardless of "on"/"off"/skipped below -- this only
        # cares about installed_version itself, not whether an update is
        # pending. See _check_and_advance_installed_baseline's own
        # docstring for the full reasoning (placeholder/falsy exclusion,
        # comparison-before-advance ordering) -- shared with async_start's
        # own startup sweep and _async_periodic_recheck.
        #
        # Skipped when the caller already ran this for the exact same
        # entity_id and state a moment ago (async_start's own startup
        # sweep, synchronously, with no await in between): running it here
        # too would silently re-fire the exact same transition again.
        # `retroactive` (only ever True when passed by that same startup
        # sweep, see this method's own call sites) matters for exactly that
        # re-fire: found live, 2026-09-03, a Home Assistant Core update
        # installed via HA's own more-info dialog showed up in History as
        # install method "external" instead of "manual". Installing Core
        # always restarts Home Assistant to take effect, which wipes
        # rollout_manager.py's own in-memory record of who requested it
        # before the transition is ever observed; the startup sweep's own
        # retroactive call already accounts for exactly that (see
        # __init__.py's own _on_install: retroactive always falls back to
        # the safe "manual" default, never guesses "external" from an
        # untrustworthy signal), but that call is itself routinely
        # suppressed by _within_startup_grace right at process start,
        # without advancing the baseline, only for this same call to
        # immediately re-fire the unsuppressed transition. Still
        # reproducible live, 2026-10-09 (every Core update kept showing
        # "external", regardless of who requested it) because this line
        # hardcoded retroactive=False on that re-fire regardless of why it
        # was needed, mislabeling the sweep's own already-suppressed
        # retroactive transition as a brand new live one -- __init__.py's
        # own _on_install only trusts was_manually_requested()/
        # state.context.user_id for a live read, both already wiped by the
        # restart by the time this ran. Passing the sweep's own intent
        # through instead keeps this re-fire retroactive too, so it's
        # re-suppressed (not misattributed) if still within the grace
        # window, and correctly logged as "manual" by the periodic recheck
        # once that window passes -- never skipped outright either (a
        # since-reverted earlier attempt at exactly that left the
        # transition missing from History entirely, not just
        # misattributed, see async_start's own startup sweep comment).
        if not baseline_already_checked:
            self._check_and_advance_installed_baseline(entity_id, state, retroactive=retroactive)

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
                    await self._cache_skipped(entity_id, state, current, latest)
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
        if self._within_startup_grace() and self._last_installed_version.get(self._stable_key(entity_id)) == latest:
            # This entity claims it still needs updating to a version we
            # ourselves already confirmed it was at, before this restart.
            # See _within_startup_grace's own docstring. Leave whatever was
            # already cached (nothing, on a fresh restart) alone rather than
            # listing it as ready to update on the strength of a reading
            # that's very likely just an upstream integration not having
            # caught up yet; a later, correct refresh (this grace window
            # elapsing, or the entity's own next real state_changed) settles
            # it either way.
            self.cache.pop(entity_id, None)
            return
        await self._async_cache_active(entity_id, state, current, latest)

    async def _async_get_available_since(self, entity_id: str, latest_version: str, size: Size) -> datetime:
        """The authoritative "when did an update this size or smaller first
        become available since the last real install", read from
        self._available_since (see __init__'s own comment) whenever it
        already has a record whose own max_size is still at least as big
        as `size`, so a later restart/availability blip/integration reload
        can never quietly re-derive a different answer, and a same-or-
        smaller supersession (e.g. 2.0.0 -> 2.0.1, both "large" against the
        same installed version) never restarts the clock either -- issue
        #17, found live, 2026-11-22: resetting this on every version bump,
        however small, could indefinitely postpone an update that happens
        to get frequent small follow-up releases.

        Only resets (falls through to _async_available_since's best-effort
        recorder lookup, same as the very first time this entity is ever
        seen) once `size` is genuinely bigger than the stored record's own
        max_size -- a newly available version that turns out to be a
        bigger jump than anything seen since the last install is a new
        risk, and gets its own full consideration time rather than
        inheriting a smaller update's nearly-spent one (direct user
        feedback on issue #17, confirming this follow-up scenario)."""
        key = self._stable_key(entity_id)
        record = self._available_since.get(key)
        if record is not None:
            stored_max_size: str | None = record.get("max_size")
            # None covers both a record persisted before this field existed
            # and async_reset_available_since's own deliberate re-anchor
            # (just as fresh a start as a brand-new entity, nothing yet to
            # compare `size` against either) -- either way, trust this
            # anchor once more and start tracking max_size from here on,
            # rather than treating "no recorded size yet" as license to
            # reset.
            if stored_max_size is None or size_rank(size) <= size_rank(cast(Size, stored_max_size)):
                parsed = dt_util.parse_datetime(record.get("since", ""))
                if parsed is not None:
                    if record.get("version") != latest_version or stored_max_size != size:
                        record["version"] = latest_version
                        record["max_size"] = size
                        await self._available_since_store.async_save(self._available_since)
                    return parsed

        available_since = await _async_available_since(self.hass, entity_id, latest_version)
        self._available_since[key] = {
            "version": latest_version,
            "since": available_since.isoformat(),
            "max_size": size,
        }
        await self._available_since_store.async_save(self._available_since)
        return available_since

    async def async_reset_available_since(self, entity_id: str, to_version: str) -> None:
        """Re-anchors to_version's own available_since to right now.
        Called by install_manager.py once a postponed-for-a-newer-HA-Core
        update resolves (self._postponed's own comment), direct user
        feedback, 2026-11-02: the staging wait period (small/medium/large)
        should start counting once an update is actually actionable, not
        run invisibly in parallel with however long it sat blocked on the
        HA Core requirement. Otherwise an update postponed for weeks
        could clear its entire wait period, or even come out already
        "ready", the moment HA Core itself updates, never having had a real
        chance for problems to surface while it was genuinely installable.
        Overwriting self._available_since[key] here is safe and durable the
        same way _async_get_available_since's own one-time backfill is: the
        next staging check for this exact to_version reads this record
        before ever falling through to a fresh recorder lookup, so this new
        anchor sticks instead of being silently re-derived back to the
        original, pre-postponement date.

        No max_size set here on purpose: _async_get_available_since treats
        that the same as a pre-issue-#17 record, trusting this fresh anchor
        once more and starting to track max_size from whatever size is
        checked next, exactly the clean-slate re-anchor this method is
        already documented above to be."""
        key = self._stable_key(entity_id)
        self._available_since[key] = {"version": to_version, "since": dt_util.utcnow().isoformat()}
        await self._available_since_store.async_save(self._available_since)

    def _is_force_ready(self, entity_id: str, latest: str) -> bool:
        record = self._force_ready.get(self._stable_key(entity_id))
        return record is not None and record.get("version") == latest

    def _staging_result(
        self, entity_id: str, latest: str, size: Size, available_since: datetime, now: datetime, rules: StagingRules
    ) -> StagingResult:
        """The panel's own "Ready now" button (see self._force_ready's own
        comment) overrides the normal wait-days verdict for this one
        entity/version pair -- shared by _staged_result's own two callers
        (_recompute_all and _async_cache_active) via that method, found by
        code review, 2026-08-10 (both used to inline the exact same
        three-line branch independently)."""
        if self._is_force_ready(entity_id, latest):
            return StagingResult("ready", None)
        return evaluate_staging(size, available_since, now, rules)

    def _staged_result(
        self, entity_id: str, latest: str, size: Size, available_since: datetime, now: datetime, rules: StagingRules
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
        if self._is_force_ready(entity_id, latest):
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
        # Provably non-None here: evaluate_staging (inside
        # _staging_result above) only ever produces "ready"/"waiting",
        # the two statuses the early return at this method's own top
        # already filtered down to, when its own, identically-sourced
        # wait_for_size(rules, size) call came back non-None (a None wait
        # means "blocked" instead, see evaluate_staging's own body).
        wait = wait_for_size(rules, size)
        assert wait is not None
        wait_deadline = available_since + wait
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

    def _resolve_ready_since(
        self, entity_id: str, latest: str, size: Size, available_since: datetime, rules: StagingRules, status: str
    ) -> str | None:
        """The real instant this entity/version pair actually stopped
        "waiting" -- shown on the panel's own "Ready to update" timeline
        step once done (see the panel's own _buildTimeline docstring).

        A pure function of already-known, unchanging facts (available_since,
        this size's own configured wait, the postponement schedule, and
        whether "Ready now" was ever clicked for this exact version),
        recomputed fresh on every call, deliberately never stored -- same
        reasoning already settled for ready_at itself (see
        _derive_status_fields's own docstring): a stored instant can only
        ever go stale relative to a later settings/schedule change, a
        freshly-derived one never can. This mirrors _staged_result's own
        force_ready/wait_deadline/schedule-gate logic exactly (not a
        separate reimplementation) because it has to reach the exact same
        verdict that produced `status` in the first place.

        None only when genuinely nothing to show: still "waiting" (hasn't
        happened yet), this size's own wait is configured to permanently
        block (no wait period to resolve at all, see evaluate_staging's own
        "blocked" branch), or (the one real gap) a "Ready now" override
        recorded before self._force_ready gained its own "at" timestamp,
        whose actual click time was simply never persisted."""
        if status == "waiting":
            return None
        if self._is_force_ready(entity_id, latest):
            record = self._force_ready.get(self._stable_key(entity_id)) or {}
            return record.get("at")
        wait = wait_for_size(rules, size)
        if wait is None:
            return None
        wait_deadline = available_since + wait
        if self._schedule_active:
            target = next_allowed_ready(self.schedule, dt_util.as_local(wait_deadline))
            if target is not None:
                return target.isoformat()
        return wait_deadline.isoformat()

    def _status_with_postponed_override(self, entity_id: str, status: str) -> str:
        """Reported as "waiting", same as a staging-wait Postponed entity,
        not the staging-only "ready" the caller would otherwise use. See
        self._is_postponed's own comment. Shared by _derive_status_fields
        (status_now's own fresh-per-request path) and _async_cache_active
        (the actual self.cache write on every live state_changed event).
        Found live, 2026-11-02: patching only the first of those left
        sensor.py's own per-status counts and staging_skip.py's
        hide_postponed check (both read self.cache directly, never through
        status_now) still seeing the unpatched "ready", while the panel
        itself (which does go through status_now) already showed
        "Postponed" correctly: same underlying fact, two different
        answers depending on which path asked.

        Only overrides "ready": a "blocked" entity (community-held-back)
        couldn't have reached a real install attempt in the first place, so
        the two shouldn't actually co-occur, but leaving "blocked" as-is
        here is the safer choice if they somehow did."""
        return "waiting" if status == "ready" and self._is_postponed(entity_id) else status

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
        ready_since = self._resolve_ready_since(
            entity_id, cached["latest_version"], cached["version_size"], available_since, self.rules, result.status
        )
        status = self._status_with_postponed_override(entity_id, result.status)
        return {"status": status, **_cache_timing_fields(result, now), "ready_since": ready_since}

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

    def _held_back_by_community(self, entity_id: str, trusted_vote: str | None, verdict: dict | None) -> bool:
        """community_blocks_auto_install, with this coordinator's own
        whitelisted_entities already applied -- shared by export_entry,
        _async_refresh_community_verdict, and _cache_skipped below, each
        of which otherwise repeated this exact 3-argument call (found by
        /simplify review). See announcer.community_blocks_auto_install's
        own docstring for what this field itself means."""
        return community_blocks_auto_install(
            trusted_vote, (verdict or {}).get("problematic_count", 0), _is_whitelisted_for_auto_install(entity_id, self.whitelisted_entities)
        )

    def export_entry(self, cached: dict, now: datetime | None = None) -> dict:
        """One cache entry's own facts, with status/remaining_seconds/
        ready_at overridden by status_now's own fresh derivation -- the one
        place that merge happens, shared by websocket_api.py's own
        _handle_updates and diagnostics.py, which both need exactly this
        same "cached facts + fresh verdict" shape for their own response."""
        return {**cached, **self.status_now(cached, now)}

    async def _async_cache_active(self, entity_id: str, state: State, current: str, latest: str) -> None:
        # Corrected, not the raw state attribute: _known_prerelease's own
        # lookup must agree with whichever (owner, repo) remember_release_
        # prerelease actually recorded under, which is itself built from
        # this same corrected URL (the frontend/websocket_api.py's own
        # release-notes fetch always works from release_url_for_entity's
        # own output, never the raw attribute. Core's own native
        # release_url isn't even a GitHub URL at all, so the raw attribute
        # would never match anything remembered for it.
        corrected_release_url = release_url_for_entity(self.hass, entity_id, state.attributes.get("release_url"), latest)
        size = classify_version_size(current, latest, known_prerelease=self._known_prerelease(corrected_release_url, latest))
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
            available_since = await self._async_get_available_since(entity_id, latest, size)
        # available_since is still computed normally above either way, it's
        # a real fact used elsewhere (History); only the derived status/
        # remaining is overridden, see _staging_result's own comment.
        result = self._staged_result(entity_id, latest, size, available_since, now, rules)
        ready_since = self._resolve_ready_since(entity_id, latest, size, available_since, rules, result.status)
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
        # Whatever's already cached, synchronously, no fetch -- same
        # reasoning as community_verdict above. Read-only: this never
        # submits anything to community-votes, see
        # _async_refresh_firmware_version_display's own docstring for why
        # submission is deliberately triggered elsewhere (an install-
        # completion listener), not from here.
        installed_version_real, latest_version_real, _ = real_versions_for_entity(
            self.hass, entity_id, current, latest, self._firmware_version_manager
        )
        if self._firmware_version_manager is not None:
            self.hass.async_create_task(
                self._async_refresh_firmware_version_display(entity_id, current, latest)
            )
        self.cache[entity_id] = {
            "entity_id": entity_id,
            "installed_version": current,
            "latest_version": latest,
            "version_size": size,
            "installed_version_real": installed_version_real,
            "latest_version_real": latest_version_real,
            "version_size_real": _version_size_real(installed_version_real, latest_version_real),
            "status": self._status_with_postponed_override(entity_id, result.status),
            **_cache_timing_fields(result, now),
            "ready_since": ready_since,
            "installable": installable,
            # Corrected here (not left to the frontend to read state.attributes
            # itself) specifically for Core -- see release_url_for_entity's own
            # docstring for the real bug this fixes: Core's own native
            # release_url is a fixed "always latest" URL, never version-
            # specific, useless for the GitHub release-notes fallback fetch
            # and actively wrong once a newer version comes out. A no-op for
            # every other entity (OS/Supervisor/anything else), returns
            # whatever state already had. Computed once, above, and reused
            # here rather than calling this twice.
            "release_url": corrected_release_url,
            # Exposed mainly so the recorder lookup above can actually be
            # checked by hand (diagnostics download) instead of only being
            # inferable from status/remaining_seconds.
            "available_since": available_since.isoformat(),
            # Core/Supervisor/HAOS, plus whatever the user picked themselves:
            # always manual, regardless of the size/auto-install settings --
            # install_manager.py checks this before ever auto-installing.
            # Doesn't change size/status here, those stay informational.
            "auto_install_excluded": _is_excluded_from_auto_install(entity_id, self.excluded_entities),
            "auto_install_whitelisted": _is_whitelisted_for_auto_install(entity_id, self.whitelisted_entities),
            "native_auto_update": has_native_auto_update(state),
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
            # Computed once here, server-side, from the same inputs the
            # panel already has. Replaces its own former client-side
            # copy of this exact precedence (communityBlocksAutoInstall,
            # found duplicating announcer.py's own effective_auto_install_state
            # by code review, 2026-07-29). See
            # announcer.community_blocks_auto_install's own docstring for
            # the two real bugs that duplication already produced once.
            "held_back_by_community": self._held_back_by_community(entity_id, trusted_vote, community_verdict),
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
            # Kept in sync with the fields above, not just set once at the
            # initial cache build: this exact async refresh is what makes
            # community_verdict/trusted_vote go stale in the first place,
            # held_back_by_community would silently follow if left alone
            # here.
            cached["held_back_by_community"] = self._held_back_by_community(entity_id, trusted_vote, verdict)

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

    async def _async_refresh_firmware_version_display(
        self, entity_id: str, installed_version: str | None, latest_version: str | None, *, force: bool = False
    ) -> None:
        """Its own task, fired from _async_cache_active's own synchronous-
        peek block, same "patch in place once the real fetch resolves"
        shape as _async_refresh_community_verdict -- purely read-only
        display refresh, never submits anything. Harmless no-op for a
        non-Zigbee entity, or one with no device at all --
        real_versions_for_entity's own early returns handle that.

        Submission is deliberately NOT triggered from here (or from any
        other per-tick/per-refresh hook): direct user feedback, 2026-11-24,
        after a real first-boot burst where every pre-existing Zigbee
        device on the network submitted at once, purely because this
        feature had simply never checked them before -- not because
        anything had actually just changed. Submission now only ever fires
        in reaction to a genuine install completing, see
        async_check_firmware_version_submission below, registered as this
        coordinator's own install listener.

        force=True bypasses FirmwareVersionManager's own hour-long
        freshness window -- see async_force_refresh_firmware_versions
        below, the only caller that ever passes this."""
        if self._firmware_version_manager is None:
            return
        manufacturer_model_id = resolve_zigbee_manufacturer_model_for_entity(self.hass, entity_id)
        if manufacturer_model_id is None:
            return
        manufacturer, model_id = manufacturer_model_id

        await self._firmware_version_manager.async_get_versions(manufacturer, model_id, force=force)
        installed_version_real, latest_version_real, _ = real_versions_for_entity(
            self.hass, entity_id, installed_version, latest_version, self._firmware_version_manager
        )

        cached = self.cache.get(entity_id)
        if (
            cached is not None
            and cached.get("latest_version") == latest_version
            and cached.get("installed_version") == installed_version
        ):
            cached["installed_version_real"] = installed_version_real
            cached["latest_version_real"] = latest_version_real
            cached["version_size_real"] = _version_size_real(installed_version_real, latest_version_real)

    async def async_force_refresh_firmware_versions(self, recent_entity_ids: set[str]) -> None:
        """Bypasses FirmwareVersionManager's own hour-long freshness window
        and immediately re-evaluates every update entity's own display data,
        not just currently-active ones (see
        _async_refresh_firmware_version_display's own docstring for why
        this can't be scoped to self.cache the way
        async_force_refresh_community_verdicts is), same "a manual
        refresh should do both kinds of refresh, not just read whatever's
        already cached" intent as that method, direct user feedback.

        Also retries the submission check, reusing
        async_check_firmware_version_submission_for_current_install
        exactly as install_manager.py's own async_dispatch_install does,
        direct user feedback, 2026-11-25: the install-completion listener's
        own grace period (_FIRMWARE_SUBMISSION_INTERVIEW_GRACE) is a
        bounded, one-shot wait, not a retry loop, by design, so a
        Zigbee2MQTT device that hasn't re-interviewed by the time it
        elapses never gets a second chance on its own. A manual refresh
        click gives the user one, on demand, without waiting for another
        install.

        Scoped to recent_entity_ids (websocket_api.py's own caller, from
        install_log.py's own entity_ids_installed_since), not every
        entity found live, 2026-11-25: this used to retry the submission
        check for literally every Zigbee update entity on every refresh
        click, and a real refresh ended up submitting three completely
        unrelated devices at once, each one installed weeks earlier,
        purely because nothing had ever checked them before, the exact
        "every pre-existing device submits at once" risk this feature was
        always meant to stay away from (see
        _async_refresh_firmware_version_display's own docstring below),
        just reached by a different door than the one already guarded
        against. A manual click being deliberate doesn't make submitting
        on behalf of a device the user wasn't even looking at any less
        surprising. Display refresh itself stays unscoped (read-only,
        no external side effect either way)."""
        if self._firmware_version_manager is None:
            return

        async def _refresh_one(entity_id: str) -> None:
            state = self.hass.states.get(entity_id)
            if state is None:
                return
            await self._async_refresh_firmware_version_display(
                entity_id,
                state.attributes.get("installed_version"),
                state.attributes.get("latest_version"),
                force=True,
            )
            if entity_id in recent_entity_ids:
                await self.async_check_firmware_version_submission_for_current_install(entity_id)

        await asyncio.gather(
            *(_refresh_one(entity_id) for entity_id in self.hass.states.async_entity_ids("update"))
        )

    async def async_check_firmware_version_submission(
        self, entity_id: str, old_version: str | None, old_version_real: str | None
    ) -> None:
        """Registered as this coordinator's own install listener (see
        __init__.py's own call to async_add_install_listener) -- the only
        place a firmware-version pairing is ever submitted from, fired
        once per genuine install completion, never from a general per-tick
        scan (see _async_refresh_firmware_version_display's own docstring
        for why that distinction matters, direct user feedback, 2026-11-24).

        old_version/old_version_real are this same entity's own
        just-left-behind raw integer and its real version if already known
        -- see the extra same_value_for_different_raw check below for why
        this specific pair matters, on top of real_versions_for_entity's
        own cross-table check.

        Waits _FIRMWARE_SUBMISSION_INTERVIEW_GRACE before checking: a
        Zigbee2MQTT-managed device's own `sw_version` typically only
        catches up with its freshly-installed firmware once Z2M has
        re-interviewed it, which doesn't necessarily happen in the same
        instant installed_version itself changes -- a bounded, one-shot
        wait, not a retry loop; missing the window just means this one
        occurrence goes unlearned, no different from today's status quo
        before this feature existed at all.

        submission_candidate (see firmware_version_discovery.py's own
        real_versions_for_entity) already guarantees community-votes'
        workflow would accept this cleanly -- a real version-shaped string,
        and a raw integer genuinely missing from the table, never one that
        conflicts with an already-recorded value -- so by the time this
        actually submits, there's nothing left for the Action to reject.
        That cross-table check can't catch everything though: a model's
        very first-ever submission has nothing in the table yet to
        disagree with, so a Zigbee2MQTT device whose own sw_version got
        stuck right after this exact install (confirmed live, 2026-11-24,
        direct user feedback: "hoe voorkomen we dat we te vroeg een nieuw
        nummer aan dezelfde (oude?) versie koppelen?") would otherwise
        sail straight through. old_version/old_version_real close that
        specific gap: compared against the new candidate below the same
        way real_versions_for_entity already compares a jump's own two
        sides, using this one device's own just-left-behind reading
        instead of the shared table, which needs no pre-existing entry at
        all to catch a repeat.

        No local "did I already submit this" record at all (an earlier
        version of this had one, Store-backed) -- replaced with a live
        GitHub check right before ever submitting (see
        firmware_version_submit.py's own async_has_pending_submission),
        direct user feedback, 2026-11-24: "kunnen we dit niet slimmer
        maken? zodat we die cache niet nodig hebben?". The table itself is
        force-refreshed first (bypassing its own hour-long cache) for the
        same reason -- the authoritative, always-live source is checked
        directly instead of trusting local state to still be accurate."""
        if self._firmware_version_manager is None:
            return
        if resolve_zigbee_manufacturer_model_for_entity(self.hass, entity_id) is None:
            return
        await asyncio.sleep(_FIRMWARE_SUBMISSION_INTERVIEW_GRACE.total_seconds())

        state = self.hass.states.get(entity_id)
        if state is None:
            return
        installed_version = state.attributes.get("installed_version")
        latest_version = state.attributes.get("latest_version")
        manufacturer_model_id = resolve_zigbee_manufacturer_model_for_entity(self.hass, entity_id)
        if manufacturer_model_id is None:
            return
        manufacturer, model_id = manufacturer_model_id

        await self._firmware_version_manager.async_get_versions(manufacturer, model_id, force=True)
        _, _, submission_candidate = real_versions_for_entity(
            self.hass, entity_id, installed_version, latest_version, self._firmware_version_manager
        )
        if submission_candidate is None:
            return
        _, _, raw_version, real_version, _ = submission_candidate
        if same_value_for_different_raw(
            parse_zigbee_ota_version(old_version), old_version_real, raw_version, real_version
        ):
            return
        await self._async_submit_firmware_candidate(entity_id, submission_candidate)

    async def async_check_firmware_version_submission_for_current_install(self, entity_id: str) -> None:
        """Called from install_manager.py's own async_dispatch_install,
        right before the actual update.install service call for a genuine
        install (manual, auto, or a queued rollout entry, every real
        install path funnels through that one call), and from
        async_force_refresh_firmware_versions above (a manual refresh
        click's own retry), the counterpart to
        async_check_firmware_version_submission above, but for the version
        about to be left behind rather than the one an install just
        produced.

        Why this needs its own path: submission has normally only ever
        reacted to a genuine install *completing*, learning
        whatever version an install just produced. A device's starting
        firmware, whatever it was already running before this feature
        (or this entity) was ever observed completing an install here,
        never gets that same reactive moment, and once the device actually
        updates away from it, its live sw_version can never attest to that
        raw integer again (see firmware_version_discovery.py's own module
        docstring: a device's own sw_version only ever describes what it's
        running *right now*). Dispatch time, right before the version
        actually changes, is the last possible moment that pairing is still
        observable at all.

        No sleep, unlike the grace period above: this version has already
        been settled on for a while (not just freshly flashed), so there's
        no analogous "hasn't been re-interviewed yet" risk to wait out. No
        old_version comparison either, that one exists purely to catch a
        just-flashed, not-yet-settled sw_version repeating what it reported
        for the version it just left; there's no such freshly-changed state
        here at all, this reads the one that's about to become old.
        "Already have it" is still covered for free, same as any other
        candidate: real_versions_for_entity's own submission_candidate is
        only ever set when the raw integer is genuinely missing from the
        table (see that function's own docstring).

        Safe to call from anywhere already awaited (both callers above),
        since nothing races the state read below here. install_manager.py's
        own async_dispatch_install is different: there, the state read
        needs to happen synchronously before update.install, not from
        inside a detached background task awaited later, so it calls
        snapshot_firmware_version_submission_candidate and
        async_submit_firmware_version_submission_candidate (both below)
        directly instead of this combined method, split for exactly that
        reason (found by code review: a detached task calling this combined
        method could run its own state read at any point during or after
        that same install, seeing the entity's already-updated
        installed_version/latest_version instead of the ones this is
        actually meant to capture)."""
        snapshot = self.snapshot_firmware_version_submission_candidate(entity_id)
        if snapshot is None:
            return
        await self.async_submit_firmware_version_submission_candidate(entity_id, snapshot)

    def snapshot_firmware_version_submission_candidate(
        self, entity_id: str
    ) -> tuple[str, str, str | None, str | None] | None:
        """The synchronous part of
        async_check_firmware_version_submission_for_current_install above
        (see its own docstring for why this is split out): (manufacturer,
        model_id, installed_version, latest_version) for entity_id's own
        current firmware pairing, or None when there's nothing to check at
        all (not a Zigbee-identified entity, or firmware tracking isn't
        configured). Must be captured synchronously, before anything else
        changes entity_id's own live state."""
        if self._firmware_version_manager is None:
            return None
        manufacturer_model_id = resolve_zigbee_manufacturer_model_for_entity(self.hass, entity_id)
        if manufacturer_model_id is None:
            return None
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        manufacturer, model_id = manufacturer_model_id
        return manufacturer, model_id, state.attributes.get("installed_version"), state.attributes.get("latest_version")

    async def async_submit_firmware_version_submission_candidate(
        self, entity_id: str, snapshot: tuple[str, str, str | None, str | None]
    ) -> None:
        """The async, network-bound part of
        async_check_firmware_version_submission_for_current_install above
        (see its own docstring for why this is split out): checks a
        snapshot already captured by
        snapshot_firmware_version_submission_candidate against the shared
        firmware-versions table and submits it if it's genuinely new.
        Nothing here reads entity_id's live state anymore, so this is the
        one part that's actually safe to run from a detached background
        task."""
        manufacturer, model_id, installed_version, latest_version = snapshot
        await self._firmware_version_manager.async_get_versions(manufacturer, model_id, force=True)
        _, _, submission_candidate = real_versions_for_entity(
            self.hass, entity_id, installed_version, latest_version, self._firmware_version_manager
        )
        if submission_candidate is None:
            return
        await self._async_submit_firmware_candidate(entity_id, submission_candidate)

    async def _async_submit_firmware_candidate(
        self, entity_id: str, submission_candidate: tuple[str, str, int, str, str | None]
    ) -> None:
        """The actual GitHub submission, shared by both
        async_check_firmware_version_submission (reacting to a completed
        install) and async_check_firmware_version_submission_for_current_install
        (reacting to one about to start), found by /simplify-style review
        while adding the second caller: identical auth/lock/authoritative-
        check/submit sequence, only how submission_candidate itself gets
        produced differs between the two."""
        submission_manufacturer, submission_model_id, raw_version, real_version, submission_model_name = submission_candidate
        if self._github_auth_manager is None:
            return
        # Serializes every submission this one instance ever attempts,
        # regardless of key -- found live, 2026-11-24: two devices sharing
        # a model but sitting on two different (both genuinely new) raw
        # versions each target the same remote firmware-versions/<manufacturer>/
        # <model_id>.json file, a real write race community-votes' own retry
        # logic doesn't always absorb under enough simultaneous load.
        # Submissions are rare (only ever once per genuine install), so
        # serializing all of them costs nothing in practice.
        async with self._firmware_submission_lock:
            if not self._github_auth_manager.is_linked:
                return
            access_token = await self._github_auth_manager.async_get_valid_access_token()
            if access_token is None:
                return
            try:
                # Authoritative, not FirmwareVersionManager's own cached
                # table (already re-checked above via force=True, but that
                # still reads raw.githubusercontent.com, a CDN confirmed to
                # lag a just-written file by minutes -- direct user
                # feedback, 2026-11-24: "als het al bekend is is een issue
                # niet nodig". Re-verifying against GitHub's own backend
                # directly, right here, right before ever submitting,
                # catches a pairing this exact household (or another)
                # already wrote moments ago that the cached table simply
                # hasn't caught up to yet.
                authoritative_path = (
                    f"firmware-versions/{submission_manufacturer}/{slugify_zigbee_model(submission_model_id)}.json"
                )
                authoritative_table = (
                    await async_fetch_authoritative_json(self.hass, access_token, authoritative_path) or {}
                )
                if str(raw_version) in authoritative_table:
                    return
                if await async_has_pending_submission(
                    self.hass, access_token, submission_manufacturer, submission_model_id, raw_version
                ):
                    # Already submitted (by this instance moments ago, or
                    # another one entirely) and still being processed --
                    # let that one run its course instead of duplicating it.
                    return
                await async_submit_firmware_version(
                    self.hass,
                    access_token,
                    submission_manufacturer,
                    submission_model_id,
                    raw_version,
                    real_version,
                    self._integration_version or "unknown",
                    model_name=submission_model_name,
                )
            except Exception:
                # Silent, debug-level only -- this fires automatically,
                # with no human decision moment behind it to surface an
                # error to, same reasoning as firmware_version_submit.py's
                # own docstring.
                _LOGGER.debug("Couldn't submit firmware version for %s", entity_id, exc_info=True)

    async def _cache_skipped(self, entity_id: str, state: State, current: str, latest: str) -> None:
        # No staging computation here (state itself is "off", not "on" --
        # never ran through _async_cache_active), but available_since is
        # still a real, persisted fact (self._available_since), not
        # something only self.cache would know. Found live, 2026-08-19:
        # this used to carry over self.cache's own previous value instead,
        # which is unpersisted and empty on every restart, so a skipped
        # update's available_since silently reset to "now" after every
        # single restart, unconditionally, nothing to do with renaming.
        #
        # Read-only, unlike _async_cache_active's own
        # _async_get_available_since call -- deliberately never falls
        # through to a fresh recorder lookup here. Found live, 2026-08-19,
        # a second time: that fallback (history.get_significant_states, via
        # a recorder executor job) hung the Skip/Unskip websocket handlers
        # outright when the recorder's own executor pool was busy, since
        # both handlers await this whole refresh before ever sending a
        # response -- an infinite spinner, not just a slow one. A skipped
        # entity has no staging/wait-period computation to feed at all
        # (see this method's own docstring above), so a precise, first-time
        # answer isn't worth that risk here the way it is for a genuinely
        # pending update.
        previous = self.cache.get(entity_id)
        record = self._available_since.get(self._stable_key(entity_id))
        # No exact-version match required (issue #17's own fix, applied
        # here too for the same reason): this is a plain read of whatever
        # _async_get_available_since's own logic already decided is the
        # right anchor, not a second opinion of its own, so there's nothing
        # left to re-derive a fresher value for even when the exact target
        # version has moved on since.
        if record is not None:
            available_since = record["since"]
        else:
            available_since = previous["available_since"] if previous else dt_util.utcnow().isoformat()
        # ready_since has no equivalent persisted store of its own to fall
        # back on the way available_since just above now does -- a skipped
        # entity never runs through _resolve_ready_since (no staging
        # computation here at all), so whatever it last resolved to is the
        # closest real fact still available, None if it never had one.
        # Same already-accepted imprecision as before (neither checks
        # previous's own latest_version still matches).
        ready_since = previous.get("ready_since") if previous else None
        # Corrected, same reasoning as _async_cache_active's own comment on
        # this exact line: the raw state attribute can't ever match what
        # remember_release_prerelease recorded for this entity.
        corrected_release_url = release_url_for_entity(self.hass, entity_id, state.attributes.get("release_url"), latest)
        self.cache[entity_id] = {
            "entity_id": entity_id,
            "installed_version": current,
            "latest_version": latest,
            "version_size": classify_version_size(current, latest, known_prerelease=self._known_prerelease(corrected_release_url, latest)),
            # Not fetched for a skipped entity, same "not this slice's
            # target" reasoning as community_verdict just below -- only
            # ever carried over from previous.
            "installed_version_real": previous.get("installed_version_real") if previous else None,
            "latest_version_real": previous.get("latest_version_real") if previous else None,
            "version_size_real": previous.get("version_size_real") if previous else None,
            "status": "skipped",
            **_NO_TIMING_FIELDS,
            "ready_since": ready_since,
            "installable": bool(state.attributes.get("supported_features", 0) & UpdateEntityFeature.INSTALL),
            # Same correction as _async_cache_active's own -- see
            # release_url_for_entity's own docstring. Every cache entry gets
            # the same shape (see this method's own comment further down).
            # Computed once, above, and reused here rather than calling
            # this twice.
            "release_url": corrected_release_url,
            "available_since": available_since,
            "auto_install_excluded": _is_excluded_from_auto_install(entity_id, self.excluded_entities),
            "auto_install_whitelisted": _is_whitelisted_for_auto_install(entity_id, self.whitelisted_entities),
            "native_auto_update": has_native_auto_update(state),
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
            # trusted_vote itself isn't tracked as its own top-level field
            # here (this entry has no live community-verdict refresh of
            # its own to keep it current), only ever carried over from
            # previous the same way community_verdict just above already
            # is, purely to feed this one computation.
            "held_back_by_community": self._held_back_by_community(
                entity_id,
                previous.get("trusted_vote") if previous else None,
                previous.get("community_verdict") if previous else None,
            ),
        }
