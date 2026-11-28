"""Wires announcer.py's pure decisions into real behaviour: persists pending
auto-install announcements (Store, survives restarts), runs a periodic
check, actually calls `update.install` (with `backup=True` when the entity
supports it) once an announcement's wait elapses uncancelled, and shows/
clears a `persistent_notification`. A hard install failure (see
handle_install_failure/handle_manual_install_failure below) reuses this
exact same pending-announcement mechanism for its own backoff retry (so
the rest of the system never has to tell a retry apart from a normal
countdown), and the exact same notification to report it -- deliberately
not a Repair issue, tried first and dropped the same day: redundant next
to an already-visible notification for something with no real "fix" of
its own besides the retry that's already happening on its own.
"""
from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from contextlib import nullcontext
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.components.update import UpdateEntityFeature
from homeassistant.const import __version__ as HA_CORE_VERSION
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .announcer import (
    AutoInstallContext,
    AutoInstallReason,
    AutoInstallRules,
    PendingAnnouncement,
    decide_action,
    effective_auto_install_state,
    size_auto_install_enabled,
    start_announcement,
)
from .ai_safety_check import async_run_ai_safety_check
from .const import (
    CONF_AI_SAFETY_CHECK_ENTITY_ID,
    CONF_ANNOUNCE_HOURS,
    CONF_LARGE_AUTO_INSTALL,
    CONF_MEDIUM_AUTO_INSTALL,
    CONF_SMALL_AUTO_INSTALL,
    DEFAULT_ANNOUNCE_HOURS,
    DOMAIN,
    EVENT_ANNOUNCED,
    EVENT_INSTALL_FAILED,
    localized_strings,
)
from .coordinator import UpdateManagerCoordinator
from .device_identity import is_hacs_entity
from .entity_rename import relabel_key
from .github_auth import GitHubAuthManager
from .github_release_notes import parse_release_url
from .min_ha_version_fetch import async_fetch_min_ha_version
from .rollout_manager import RolloutManager
from .semver import ha_core_version_satisfies, min_ha_version_required

_LOGGER = logging.getLogger(__name__)

# Marketplace's own one-time, per-admin "first-run warning" gate: until any
# admin opens its panel and accepts it, update.install fails with this
# translation_key for every context-less call (ours included), regardless
# of which update it's for. No min-version-style structured detail to
# extract here, just a reason to label this specific failure with a
# clearer message than the generic one (see _FAILED_NOTIFICATION_STRINGS's
# own "item_warning_not_accepted").
_MARKETPLACE_WARNING_NOT_ACCEPTED_KEY = "warning_not_accepted"


def install_service_data(hass: HomeAssistant, entity_id: str) -> dict[str, Any]:
    """The update.install service_data for entity_id, requesting a backup
    exactly when its own supported_features says it can provide one --
    never a frontend-supplied flag (found live, 2026-11-18, see
    websocket_api.py's own _handle_install docstring for the real bug this
    already fixed once). Shared by this module's own _async_execute and
    websocket_api.py's _handle_install, which each had their own identical
    copy of this exact check (found by /code-review)."""
    state = hass.states.get(entity_id)
    supported_features = state.attributes.get("supported_features", 0) if state else 0
    service_data: dict[str, Any] = {"entity_id": entity_id}
    if supported_features & UpdateEntityFeature.BACKUP:
        service_data["backup"] = True
    return service_data


def failure_reason_for(exception: BaseException) -> str | None:
    """The specific, labeled reason for a failed install's "Failed updates"
    notification, or None for the generic case. Shared by
    _async_run_install's own except-branch below and websocket_api.py's
    _async_run_manual_install, found duplicated verbatim by code review,
    2026-11-02, one shared place to extend if a third labeled reason is
    ever added."""
    key = getattr(exception, "translation_key", None)
    return key if key == _MARKETPLACE_WARNING_NOT_ACCEPTED_KEY else None

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_pending_installs"

_CHECK_INTERVAL = timedelta(minutes=5)
_PENDING_NOTIFICATION_ID = f"{DOMAIN}_pending_installs"
_PANEL_UPDATES_URL = "/update-manager/updates"
# How far apart consecutive EVENT_ANNOUNCED fires within the same tick are
# spaced, see self._announce_fire_count's own comment for why. 1.5s
# keeps a default `mode: queued` automation (max 10) comfortably inside
# its own max-runs window for a realistic batch size, without making a
# genuinely large batch's own total announce window noticeably long.
_ANNOUNCE_FIRE_STAGGER_SECONDS = 1.5

# hass.config.language-driven, same convention the panel's own TRANSLATIONS
# already uses (see update-manager-panel.js) -- found live there: a user with
# hass.language "en" still saw all-Dutch panel text before that was fixed,
# and this persistent_notification (the one place Update Manager announces
# a pending auto-install outside the panel) had the same bug.
#
# One notification_id total for every currently scheduled install, not one
# per announcement (or even one per batch of simultaneously-announced
# entities, an earlier version of this) -- direct user feedback,
# 2026-09-12: every separate notification piled up in the notifications
# list instead of being replaced, one for each announcement ever made.
# _refresh_pending_notification below rebuilds this from self._pending's
# own complete, current contents every time anything about it changes, so
# it always reflects the real, current picture instead of a snapshot of
# whichever entities happened to become announce-eligible at the same
# moment; cancelling one out of several no longer leaves the others'
# mention of it stale either, unlike the batch-per-tick version before it.
_NOTIFICATION_STRINGS = {
    "en": {
        "title": "Scheduled updates",
        "body": (
            "Update Manager wants to install {count} update{plural}:\n\n{items}\n\n"
            "If you don't want that, cancel any of them in [Update Manager]({url})."
        ),
        "item": "* **{name}** to version {to_version}, on {when}",
    },
    "nl": {
        "title": "Geplande updates",
        "body": (
            "Update Manager wil {count} update{plural} installeren:\n\n{items}\n\n"
            "Wil je dat niet, annuleer ze dan in [Update Manager]({url})."
        ),
        "item": "* **{name}** naar versie {to_version}, op {when}",
    },
}

# Escalating cooldown after a hard install failure (an exception from
# `update.install` itself, e.g. a download error -- distinct from
# rollout_manager.py's own "stuck" case, an install that started normally
# and simply never finished), direct user feedback 2026-10-24: a known HACS-
# wide download bug (see STANDARDS.md) made this visible live, 140 identical
# failed attempts in one day, every 5 minutes with no backoff at all. Each
# failed attempt on an already-installed repository also makes HACS itself
# do a real backup-restore cycle on disk before raising -- the actual cost
# worth backing off for, not the network request itself (confirmed against
# HACS's own async_install_repository). Capped at an hour, not longer: once
# whatever's actually broken (upstream, or this specific device) gets fixed,
# this should still notice reasonably soon, not sit quiet for a day.
#
# Represented as a perfectly normal PendingAnnouncement in self._pending
# (see handle_install_failure below), not a separate, parallel notion of
# "scheduled" -- direct user feedback, 2026-10-24: a retry after a failure
# should be indistinguishable from any other auto-install everywhere it's
# shown (the list badge, status text, sort order, the detail dialog's own
# timeline, Cancel), not a special case the frontend (or announcer.py, see
# its own decide_action) needs to separately know about. self._failure_
# counts below is the one piece of bookkeeping that genuinely can't live in
# PendingAnnouncement itself: how many consecutive failures this is, purely
# to pick the right backoff tier. No Repair issue (tried first, same day):
# redundant next to the "Failed updates" notification below, which already
# covers the exact same "something's failing" signal, and this has no real
# "fix" action of its own besides the retry that's already happening.
_FAILURE_BACKOFF_SCHEDULE = (timedelta(minutes=5), timedelta(minutes=15), timedelta(hours=1))

_FAILED_NOTIFICATION_ID = f"{DOMAIN}_failed_installs"

# Same hass.config.language convention as _NOTIFICATION_STRINGS above, and
# the same one-notification-total reasoning: rebuilt from self._failed's
# own current contents by _refresh_failed_notification, direct user
# feedback, 2026-09-12.
_FAILED_NOTIFICATION_STRINGS = {
    "en": {
        "title": "Failed updates",
        "body": (
            "Update Manager couldn't install {count} update{plural}:\n\n{items}\n\n"
            "Check the Home Assistant logs for details, or try installing manually in "
            "[Update Manager]({url})."
        ),
        "item": "* **{name}** to version {to_version}",
        "item_warning_not_accepted": (
            "* **{name}** to version {to_version}. Needs you to open Marketplace once "
            "and accept its first-run warning."
        ),
    },
    "nl": {
        "title": "Mislukte updates",
        "body": (
            "Update Manager kon {count} update{plural} niet installeren:\n\n{items}\n\n"
            "Bekijk de Home Assistant-logs voor details, of installeer handmatig in "
            "[Update Manager]({url})."
        ),
        "item": "* **{name}** naar versie {to_version}",
        "item_warning_not_accepted": (
            "* **{name}** naar versie {to_version}. Vereist dat je eenmalig Marketplace "
            "opent en de eerste-keer-waarschuwing accepteert."
        ),
    },
}


def auto_install_rules_from_options(options: dict) -> AutoInstallRules:
    return AutoInstallRules(
        small_auto_install=bool(options.get(CONF_SMALL_AUTO_INSTALL, False)),
        medium_auto_install=bool(options.get(CONF_MEDIUM_AUTO_INSTALL, False)),
        large_auto_install=bool(options.get(CONF_LARGE_AUTO_INSTALL, False)),
        announce_wait=timedelta(hours=options.get(CONF_ANNOUNCE_HOURS, DEFAULT_ANNOUNCE_HOURS)),
        ai_safety_check_entity_id=options.get(CONF_AI_SAFETY_CHECK_ENTITY_ID) or None,
    )


def _friendly_name(hass: HomeAssistant, entity_id: str) -> str:
    """A trailing " Update" (HA's own default entity name for the update
    platform, e.g. "Music Assistant Update") reads redundantly right next
    to this module's own "to version X" wording -- "Music Assistant Update
    to version 2.9.13" (direct user feedback, 2026-08-14). Stripped the
    same case-insensitive way the panel's own friendlyEntityName already
    does (update-manager-panel.js), so both surfaces agree."""
    state = hass.states.get(entity_id)
    name = state.name if state else entity_id
    return re.sub(r"\s+update$", "", name, flags=re.IGNORECASE)


class InstallManager:
    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: UpdateManagerCoordinator,
        rules: AutoInstallRules,
        rollout_manager: RolloutManager,
        github_auth_manager: GitHubAuthManager,
    ) -> None:
        self.hass = hass
        self._coordinator = coordinator
        self._rules = rules
        self._github_auth_manager = github_auth_manager
        # Gates every auto-install dispatch below, a no-op for anything
        # that isn't part of an active multi-device Zigbee rollout (see
        # rollout_manager.py's own docstring), so this is invisible for the
        # overwhelming majority of updates.
        self._rollout_manager = rollout_manager
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._pending: dict[str, PendingAnnouncement] = {}
        # entity_id -> (to_version, reason) the install was cancelled for --
        # stays quiet for that exact target, a newer version is free to
        # announce. reason is None for a plain, manual cancel (the websocket
        # handler/cancel_scheduled_install service, neither of which passes
        # one), or the AI safety check's own short explanation when that's
        # what cancelled it (async_cancel's own reason parameter).
        self._cancelled: dict[str, tuple[str, str | None]] = {}
        # entity_id -> (to_version, status, reason) for the AI safety
        # check's own non-cancelling outcomes ("passed"/"failed"). The
        # cancelling outcome already lives in self._cancelled above, no
        # second place needed for that one. Not persisted, same "meaningful
        # only for a live process" reasoning as self._failed below: purely
        # for the timeline's own display, nothing here ever gates a
        # decision, so losing it on a restart is an accepted, low-stakes gap.
        # to_version, status, reason, reason_code, notable (see
        # ai_safety_check.py's own AiSafetyCheckResult comment for what
        # each one is).
        self._ai_check_results: dict[str, tuple[str, str, str | None, str | None, bool]] = {}
        # Set by _async_announce/_async_remove/the stale-cancellation prune
        # during a tick, so _async_tick can save once at the end instead of
        # once per changed entity -- see _async_tick's own comment.
        self._dirty = False
        self._unsub_timer = None
        self._unsub_coordinator_listener: Callable[[], None] | None = None
        # Fired whenever self._pending/self._failed change, i.e. right
        # alongside _refresh_pending_notification/_refresh_failed_notification
        # (see pending_entities/failed_entities below for the two sensors
        # that read this), same async_add_listener/_fire_listeners shape
        # coordinator.py's own already uses, for consistency.
        self._listeners: list[Callable[[], None]] = []
        # entity_id -> the AutoInstallContext _async_execute just dispatched
        # update.install for -- lets __init__.py's install-listener (fired
        # once the entity's installed_version actually changes, from
        # coordinator.py) tell install_log.py whether *this* completed
        # install was auto-install's doing or a manual click elsewhere, and
        # if so, why (own rules vs. a trusted vote, and when it was
        # announced). Not persisted: only meaningful for the brief window
        # between dispatching and the entity's own state catching up.
        self._recently_executed: dict[str, AutoInstallContext] = {}
        # entity_id -> (to_version, announced_at) of the last real announce,
        # kept even after self._pending[entity_id] itself gets cleared --
        # decide_action's own RE_ANNOUNCE_COOLDOWN guard against a flapping
        # entity re-triggering "announce" (and a fresh EVENT_ANNOUNCED) every
        # time eligibility briefly recovers. Not persisted, same "meaningful
        # only for a live process" reasoning as self._recently_executed above.
        self._recently_announced: dict[str, tuple[str, datetime]] = {}
        # How many EVENT_ANNOUNCED fires this tick has already staggered --
        # reset once per _async_tick, right before its own gather (see that
        # method's own comment), then read-and-incremented by
        # _async_announce to space consecutive fires out in time. Found
        # live, 2026-11-02: a `mode: queued` automation reacting to this
        # event (the default for this project's own notifications
        # Blueprint) hit its own default max-runs-of-10 within seconds for
        # a batch bigger than that, silently dropping the rest. HA's own
        # queued-mode script.py never re-queues a rejected run, see
        # _ANNOUNCE_FIRE_STAGGER_SECONDS below for the actual spacing.
        # Safe to read-then-increment with no lock of its own: every
        # access happens on this single-threaded event loop with no await
        # between the read and the write.
        self._announce_fire_count = 0
        # entity_id -> (to_version, reason tag or None) that just failed to
        # install, purely to rebuild _refresh_failed_notification's own
        # single notification from the current, complete picture -- not
        # persisted, same "meaningful only for a live process" reasoning as
        # self._recently_executed above; a failure from a previous run
        # isn't worth resurfacing after a restart. The reason (e.g.
        # "warning_not_accepted") picks a specific notification item
        # template instead of the generic one, see _refresh_failed_
        # notification. Folded into this same dict rather than a second,
        # hand-synchronized one (found by /simplify review, 2026-11-03:
        # every touch point, rename/write/pop/read, had to update both in
        # lockstep for no storage-format reason, neither is persisted).
        self._failed: dict[str, tuple[str, str | None]] = {}
        # entity_id -> (to_version, consecutive failure count) for picking
        # the right _FAILURE_BACKOFF_SCHEDULE tier and wording the Repair
        # issue -- same "not persisted, meaningful only for a live process"
        # reasoning as self._failed above. The actual next-retry *time* this
        # drives lives in self._pending instead (a real PendingAnnouncement,
        # see handle_install_failure), which *is* persisted, same as any
        # other scheduled auto-install -- only the consecutive-count
        # bookkeeping itself resets after a restart, not the retry time a
        # user is actually shown.
        self._failure_counts: dict[str, tuple[str, int]] = {}
        # entity_id -> (to_version, required HA Core version) for an
        # install blocked by min_ha_version_required above. Deliberately
        # its own bucket, not a self._pending/self._failed entry: unlike a
        # generic failure, blindly retrying this on the usual backoff
        # schedule would cost a real backup-restore cycle (HACS/Marketplace
        # both do one before this check even runs) every single time, for
        # something we already know won't succeed until the user's own HA
        # Core version changes, see _async_evaluate_one's own postponed
        # guard, which checks that cheaply instead of reattempting.
        #
        # Persisted (found live, 2026-11-02: it originally wasn't, on the
        # assumption a restart would just cost one extra real attempt to
        # rediscover it, same as other in-memory-only bookkeeping here;
        # wrong, because _async_execute already clears self._pending for
        # this entity_id before dispatching the install that lands it here,
        # so a restart while postponed left nothing in either dict: not
        # this one, un-persisted, and not self._pending either, already
        # cleared. The entity read as a brand-new, never-evaluated update,
        # restarting its entire announce/wait cycle from scratch instead of
        # one cheap re-check, hiding a known, still-true fact for as long
        # as that whole wait period takes to elapse again).
        self._postponed: dict[str, tuple[str, str]] = {}
        # (owner, repo, tag) -> the "homeassistant" key min_ha_version_fetch.py
        # found there (or None, confirmed absent) -- a release's own
        # hacs.json can never change once published, so a confirmed answer
        # is cached here forever, never re-fetched for the same tag twice.
        # Deliberately not persisted (unlike self._postponed above): losing
        # this on a restart costs one more real GitHub fetch per still-
        # relevant tag, not a wrongly-forgotten fact.
        self._min_ha_version_cache: dict[tuple[str, str, str], str | None] = {}
        # Serializes every _async_tick pass against every other one: same
        # fix, and same underlying race, as staging_skip.py's own StagingSkipManager
        # lock (see its docstring for the full incident this closes). _on_recompute
        # schedules a brand-new _async_tick task on *every* coordinator recompute,
        # with nothing stopping a previous tick's own asyncio.gather from still
        # being in flight. Two overlapping ticks could both see the same entity's
        # self._pending as None (neither had written it yet) and both decide
        # "announce", each computing its own PendingAnnouncement independently.
        # Found by review while investigating a separate reported issue, not
        # something confirmed live yet, but the exact same shape of bug
        # staging_skip.py already had to fix once.
        self._lock = asyncio.Lock()
        # Serializes update.install dispatches for HACS/Marketplace-backed
        # entities specifically against each other (see
        # async_dispatch_install's own docstring for why it's scoped that
        # narrowly, and why it wasn't always), distinct from self._lock
        # above (which only serializes whole tick passes, not the installs
        # a single tick's own asyncio.gather fires concurrently). Found
        # live, 2026-11-02: a batch of simultaneous auto-installs (several
        # HACS integrations becoming eligible in the same tick) each called
        # update.install at the same time, and HACS's own backup step
        # (custom_components/hacs/utils/backup.py's _init_backup_dir) does a
        # shutil.rmtree on a single shared /tmp/hacs_backup directory, not a
        # per-install tempdir, so two of those running at once raced and
        # raised OSError: Directory not empty. _async_run_install is still
        # dispatched via its own hass.async_create_task (not awaited inline
        # by _async_execute), so a slow install still doesn't hold up
        # evaluating the rest of the batch; only the actual service call
        # itself now waits its turn, and (since async_dispatch_install's own
        # 2026-11-14 fix) only when it's actually a HACS-backed entity.
        # Doesn't cover RolloutManager's own Zigbee-queued dispatches
        # (rollout_manager.py's _async_dispatch, already paced per Zigbee
        # network): a different resource (the Zigbee radio, not this
        # directory), already serialized by its own, separate mechanism.
        self._install_lock = asyncio.Lock()

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self._pending = {
            entity_id: PendingAnnouncement(
                entity_id=entity_id,
                to_version=entry["to_version"],
                announced_at=dt_util.parse_datetime(entry["announced_at"]),
                execute_at=dt_util.parse_datetime(entry["execute_at"]),
            )
            for entity_id, entry in data.get("pending", {}).items()
        }
        # Backward-compatible: an older install wrote a bare to_version
        # string per entity_id, before a reason was ever recorded alongside
        # it. Read as (value, None) same as a reason-less cancel always was.
        self._cancelled = {
            entity_id: (entry, None) if isinstance(entry, str) else (entry["to_version"], entry.get("reason"))
            for entity_id, entry in data.get("cancelled", {}).items()
        }
        self._postponed = {
            entity_id: (entry["to_version"], entry["required_version"])
            for entity_id, entry in data.get("postponed", {}).items()
        }

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "pending": {
                    entity_id: {
                        "to_version": p.to_version,
                        "announced_at": p.announced_at.isoformat(),
                        "execute_at": p.execute_at.isoformat(),
                    }
                    for entity_id, p in self._pending.items()
                },
                "cancelled": {
                    entity_id: {"to_version": to_version, "reason": reason}
                    for entity_id, (to_version, reason) in self._cancelled.items()
                },
                "postponed": {
                    entity_id: {"to_version": to_version, "required_version": required_version}
                    for entity_id, (to_version, required_version) in self._postponed.items()
                },
            }
        )

    def pending_for(self, entity_id: str) -> PendingAnnouncement | None:
        return self._pending.get(entity_id)

    def postponed_for(self, entity_id: str) -> str | None:
        """The minimum HA Core version entity_id's own pending auto-install
        is still waiting for, or None if it isn't postponed for that
        reason at all. Read by websocket_api.py's own _handle_updates,
        see update-manager-panel.js's own "Postponed" badge/section."""
        postponed = self._postponed.get(entity_id)
        return postponed[1] if postponed is not None else None

    def is_cancelled(self, entity_id: str, to_version: str) -> bool:
        """Whether async_cancel was already called for this exact entity/
        version pair -- read by websocket_api.py's own _handle_updates so
        the panel can tell a genuinely cancelled "waiting" update apart
        from an untouched one. async_cancel itself already prevents the
        real announcement from ever starting (decide_action's own
        cancelled_to_version check), but before this the panel had no way
        to know that: projectedAutoInstallTime (the "will auto-install"
        badge/Cancel button/sort order) only ever looked at status/
        remaining_seconds/settings, never at this -- closing and reopening
        the dialog right after clicking Cancel showed the exact same
        projection and Cancel button back again, reading as if cancelling
        had done nothing even though it silently already had."""
        cancelled = self._cancelled.get(entity_id)
        return cancelled is not None and cancelled[0] == to_version

    def cancelled_reason(self, entity_id: str, to_version: str) -> str | None:
        """The AI safety check's own short reason this exact cancellation
        happened for, or None for a plain, reason-less manual cancel --
        read by the coordinator alongside is_cancelled above, for the
        panel's own "Cancelled: <reason>" timeline step."""
        cancelled = self._cancelled.get(entity_id)
        return cancelled[1] if cancelled is not None and cancelled[0] == to_version else None

    def ai_check_result(self, entity_id: str, to_version: str) -> tuple[str, str | None, str | None, bool] | None:
        """The AI safety check's own non-cancelling outcome ("passed"/
        "failed") for this exact entity/version, or None if it never ran
        (no ai_task configured, or to_version has since moved on). Mirrors
        is_cancelled/cancelled_reason above, read by the coordinator the
        same way. The third item is reason_code (see ai_safety_check.py's
        own AiSafetyCheckReasonCode), None for a "passed" result or a
        "failed" one with no standard, UI-displayable shape. The fourth is
        notable (see AiSafetyCheckResult's own comment): whether reason is
        actually worth showing a person, not just logging."""
        result = self._ai_check_results.get(entity_id)
        if result is None or result[0] != to_version:
            return None
        return result[1], result[2], result[3], result[4]

    @property
    def all_pending(self) -> list[PendingAnnouncement]:
        return list(self._pending.values())

    def async_start(self) -> None:
        self._unsub_timer = async_track_time_interval(self.hass, self._async_tick, _CHECK_INTERVAL)
        # Also re-evaluated on every coordinator recompute (a state_changed,
        # the periodic recheck, or a settings save), not just this class's
        # own 5-minute timer -- same mechanism staging_skip.py's own
        # _on_recompute already uses. Found by review: without this, a real
        # user skip (via HA's own UI) on an already-announced "ready" entity
        # left a stale pending_install/persistent_notification visible for
        # up to 5 minutes, since decide_action only got a chance to notice
        # the new "skipped" status on the next timer tick.
        self._unsub_coordinator_listener = self._coordinator.async_add_listener(self._on_recompute)
        # Found live, 2026-11-04: a reload/restart only ever reaches this
        # method itself, then waits for the first of the above to actually
        # fire, up to 5 minutes, for anything that depends on re-evaluating
        # pending/postponed state against conditions that may have changed
        # since this was last persisted (e.g. a stale self._pending entry
        # the postponed early-return above is now able to self-heal, but
        # only once it actually runs). Kicking one tick immediately, same
        # pattern as _on_recompute, makes that correction visible right
        # after a reload instead of only eventually.
        self.hass.async_create_task(self._async_tick(dt_util.utcnow()))

    def update_rules(self, rules: AutoInstallRules) -> None:
        """Applies newly-saved auto-install rules in place -- no reload
        needed, see coordinator.py's async_update_rules for the same
        reasoning. The next periodic tick (at most 5 minutes away) picks
        this up naturally."""
        self._rules = rules

    async def async_set_master_enabled(self, enabled: bool) -> None:
        """Applied immediately, not left to the next periodic tick (up to 5
        minutes away) -- direct user feedback (2026-07-17): pausing should
        visibly cancel any in-flight countdown (and dismiss its
        persistent_notification) right away, not just quietly stop
        advancing it in the background.

        No-ops when the value hasn't actually changed -- a settings save
        calls this both directly (websocket_api.py's save_settings handler)
        and again via HA's own config-entry update_listener, fired as an
        unawaited background task shortly after with the same value. Found
        by review: without this guard, that second, redundant tick could
        run moments after the first one just dispatched an install (an
        entity's execute_at crossed exactly at save time), see a cleared
        self._pending and a cache that hasn't caught up to the install yet,
        and wrongly start a brand-new announcement for a version already
        mid-install.

        Stores the flag on the coordinator (self._coordinator.master_enabled),
        not a private copy of its own -- see coordinator.py's own
        set_master_enabled for why."""
        if enabled == self._coordinator.master_enabled:
            return
        self._coordinator.set_master_enabled(enabled)
        await self._async_tick(dt_util.utcnow())

    async def async_force_reevaluate(self) -> None:
        """websocket_api.py's own refresh_community_verdicts handler (the
        panel's manual refresh button) calls this too, right after its own
        verdicts refresh, so the button is also a "re-check pending/
        postponed state against current conditions right now" action, not
        just the periodic timer or the next unrelated coordinator recompute.
        Found live, 2026-11-04: a stale self._pending entry (now self-healed
        by the postponed branch in _async_evaluate_one) otherwise stayed
        visible until one of those happened to fire on its own."""
        await self._async_tick(dt_util.utcnow())

    def async_retry_missing_ai_checks(self) -> None:
        """Called by coordinator.py's own periodic self-healing recheck
        (every 15 minutes, no human involved), deliberately narrower
        than async_retry_missing_or_failed_ai_checks below. Direct user
        feedback, 2026-11-27: endlessly re-running an already-failed check
        on a timer, forever, isn't "self-healing" for a failure reason
        that's an established fact about this exact release (no release
        notes exist for it, say), not a transient glitch. That would
        just hammer the same ai_task entity every 15 minutes for no
        reason, indefinitely. Only ever retries an entity that's never
        been checked at all (see the shared method's own point 2), which
        a periodic timer catching up on its own is genuinely reasonable
        for. A genuine past failure is still retried, just only by the
        manual refresh button, an explicit, one-off human action, not an
        automatic loop that never stops asking."""
        self._async_retry_ai_checks(include_previously_failed=False)

    def async_retry_missing_or_failed_ai_checks(self) -> None:
        """Called by the panel's own manual refresh button (websocket_api.py's
        refresh_community_verdicts handler), same "a manual refresh should
        also retry what's stale" intent as its other calls. Direct user
        feedback, 2026-11-27, two distinct gaps, both funneled into the
        same sequential retry below:

        1. A real, now-fixed bug left several entities' own AI safety
           check marked "failed" with no way to ever get a fresh attempt.
           Deliberately only retried here, not by the periodic recheck
           too, see async_retry_missing_ai_checks's own comment for why.
        2. An entity already pending/announced *before* an ai_task entity
           was ever configured (or before this feature even existed) never
           got a first attempt at all, not just a failed one. The check
           only ever runs once, at the moment of a fresh announcement (see
           _fire_announced), so a still-pending entity from before that
           moment existed has no entry in self._ai_check_results/
           self._cancelled whatsoever, not even a "failed" one to notice
           and retry. Confirmed live, 2026-11-27: several already-pending
           entities showed no AI-check detail at all in the timeline."""
        self._async_retry_ai_checks(include_previously_failed=True)

    def _async_retry_ai_checks(self, *, include_previously_failed: bool) -> None:
        """Re-running for the exact same still-pending to_version, not
        waiting for a newer version to come along naturally.

        One detached task overall, not one per entity: direct user
        feedback, 2026-11-27, firing every retry at once would hit the
        exact same configured ai_task entity simultaneously, worsening the
        provider-side "high demand" overload this is meant to recover
        from, not just working around it. Processed one at a time instead
        (see _async_retry_ai_checks_sequential below), same "never
        block on an ai_task call" reasoning _fire_announced's own comment
        already gives for why this whole thing is a detached task at all.
        This method itself still returns immediately either way, its two
        public callers' own response doesn't wait for any of this."""
        ai_task_entity_id = self._rules.ai_safety_check_entity_id
        if not ai_task_entity_id:
            return
        candidates: list[tuple[str, str, str]] = []
        retried_entity_ids: set[str] = set()
        if include_previously_failed:
            for entity_id, (to_version, status, _reason, _reason_code, _notable) in list(
                self._ai_check_results.items()
            ):
                if status != "failed":
                    continue
                cached = self._coordinator.cache.get(entity_id)
                from_version = cached.get("installed_version") if cached else None
                if from_version is None:
                    continue
                candidates.append((entity_id, from_version, to_version))
                retried_entity_ids.add(entity_id)
        # Whitelisted/instant entities never reach self._pending at all
        # (decide_action sends those straight to "execute", see
        # announcer.py's own docstring), so iterating this dict already
        # excludes exactly the entities this feature deliberately never
        # checks in the first place (announce_hours=0/instant means no
        # cancel-window for anyone, the AI included), with no extra
        # filtering needed.
        for entity_id, pending in self._pending.items():
            if entity_id in retried_entity_ids:
                continue
            existing = self._ai_check_results.get(entity_id)
            if existing is not None and existing[0] == pending.to_version:
                continue  # already has a real, current-version result
            cached = self._coordinator.cache.get(entity_id)
            from_version = cached.get("installed_version") if cached else None
            if from_version is None:
                continue
            candidates.append((entity_id, from_version, pending.to_version))
        if candidates:
            self.hass.async_create_task(self._async_retry_ai_checks_sequential(candidates, ai_task_entity_id))

    async def _async_retry_ai_checks_sequential(
        self, candidates: list[tuple[str, str, str]], ai_task_entity_id: str
    ) -> None:
        for entity_id, from_version, to_version in candidates:
            await self._async_handle_ai_safety_check(entity_id, from_version, to_version, ai_task_entity_id)

    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Registers a callback fired whenever self._pending/self._failed
        change (see _fire_listeners below), for sensor.py's own
        UpdateManagerPendingInstallsSensor/UpdateManagerFailedInstallsSensor.
        Same shape as coordinator.py's own async_add_listener."""
        self._listeners.append(listener)

        def _remove() -> None:
            self._listeners.remove(listener)

        return _remove

    def _fire_listeners(self) -> None:
        for listener in self._listeners:
            listener()

    def pending_entities(self) -> list[dict[str, Any]]:
        """The current self._pending contents, in the same shape
        sensor.py's own UpdateManagerPendingInstallsSensor exposes as its
        `entities` attribute, as plain dicts rather than PendingAnnouncement
        NamedTuples, so that attribute stays JSON-serializable the same way
        UpdateManagerNeedsManualActionSensor's own `entities` already is.
        Sorted by execute_at, same order _refresh_pending_notification's
        own notification already reads in."""
        return [
            {"entity_id": p.entity_id, "to_version": p.to_version, "execute_at": p.execute_at.isoformat()}
            for p in sorted(self._pending.values(), key=lambda p: p.execute_at)
        ]

    def failed_entities(self) -> list[dict[str, Any]]:
        """Same reasoning as pending_entities above, for self._failed."""
        return [
            {"entity_id": entity_id, "to_version": to_version, "reason": reason}
            for entity_id, (to_version, reason) in self._failed.items()
        ]

    @callback
    def _on_recompute(self) -> None:
        self.hass.async_create_task(self._async_tick(dt_util.utcnow()))

    @callback
    def async_stop(self) -> None:
        if self._unsub_timer is not None:
            self._unsub_timer()
            self._unsub_timer = None
        if self._unsub_coordinator_listener is not None:
            self._unsub_coordinator_listener()
            self._unsub_coordinator_listener = None

    async def async_cancel(self, entity_id: str, to_version: str, *, reason: str | None = None) -> None:
        """Cancels auto-install for this exact target version -- callable
        even before a real announcement exists yet (still "waiting", only
        projected, see the panel's own projectedAutoInstallTime), not just
        once actually "ready" and formally announced. Direct user feedback:
        seeing a "will auto-update" projection with no way to act on it
        yet read as a real gap. decide_action already checks
        cancelled_to_version == current_to_version on every tick regardless
        of status, so recording this now correctly prevents the real
        announcement from ever starting once the entity does become ready
        -- no other change needed for that half of it. `to_version` comes
        from the caller (the version currently shown in the UI), not
        necessarily from an existing PendingAnnouncement, since one might
        not exist yet. `reason` stays None for a plain, manual cancel (the
        websocket handler/cancel_scheduled_install service both still call
        this with no reason); only the AI safety check passes one."""
        self._cancelled[entity_id] = (to_version, reason)
        await self._async_remove(entity_id)
        await self._async_save()

    async def async_rename_entity(self, old_entity_id: str, new_entity_id: str) -> None:
        """Relabels this entity's pending/cancelled/in-flight auto-install
        state after a live HA entity registry rename -- see __init__.py's
        own EVENT_ENTITY_REGISTRY_UPDATED listener. PendingAnnouncement/
        AutoInstallContext are both NamedTuples, hence _replace() rather
        than mutating entity_id in place."""
        # Popped directly, not via relabel_key -- PendingAnnouncement's own
        # nested entity_id field needs _replace() either way, so
        # relabel_key's own reinsert-at-new-key step would just be
        # immediately overwritten (found by code review, 2026-08-18: dead
        # work, no bug, but pointless).
        pending = self._pending.pop(old_entity_id, None)
        if pending is not None:
            self._pending[new_entity_id] = pending._replace(entity_id=new_entity_id)
        cancelled_moved = relabel_key(self._cancelled, old_entity_id, new_entity_id) is not None
        # self._postponed is persisted too, same as self._pending/
        # self._cancelled above, found by code review, 2026-11-03: it used
        # to be relabeled below without ever joining this save condition,
        # so a rename while postponed lost that state on an untimely
        # restart (storage still had it under old_entity_id, which no
        # longer resolves to anything after the rename).
        postponed_moved = relabel_key(self._postponed, old_entity_id, new_entity_id) is not None
        if pending is not None or cancelled_moved or postponed_moved:
            await self._async_save()
        # AutoInstallContext carries no entity_id field of its own (only
        # ever looked up via this dict's own key) -- just move it.
        relabel_key(self._recently_executed, old_entity_id, new_entity_id)
        if relabel_key(self._failed, old_entity_id, new_entity_id) is not None:
            self._refresh_failed_notification()
        relabel_key(self._failure_counts, old_entity_id, new_entity_id)
        relabel_key(self._ai_check_results, old_entity_id, new_entity_id)

    async def _async_tick(self, now: datetime) -> None:
        # Every entity the coordinator currently tracks, plus any entity
        # with a leftover announcement that isn't in the cache at all
        # anymore (e.g. the update disappeared) -- the latter defaults to
        # "not ready", so decide_action correctly cleans it up.
        #
        # Concurrent, not one entity at a time -- found live (2026-07-17):
        # this tick now also runs on every coordinator recompute (see
        # async_start's own coordinator listener), not just the 5-minute
        # timer, and a settings save awaits async_set_master_enabled ->
        # this same tick directly, so a slow sequential pass here was
        # directly felt as "Save spins for a long time". Same concurrency
        # fix staging_skip.py's own equivalent passes already use.
        #
        # One save at the end, not one per entity that changed
        # (_async_announce/_async_remove/the stale-cancellation prune below
        # just mark self._dirty) -- Store.async_save writes the whole
        # pending+cancelled dict immediately, so saving per-entity inside a
        # loop of N changed entities was N full-file writes of an O(N)
        # payload in the same tick instead of one.
        #
        # The whole pass serialized against any other tick via self._lock
        # (see its own comment). Concurrency *within* one tick (the gather
        # below) is still fully parallel, only two separate ticks can no
        # longer run their own read-decide-write sequence interleaved.
        async with self._lock:
            # self._postponed included for the same reason self._pending is:
            # an entity postponed for a too-old HA Core version that then
            # drops out of coordinator.cache entirely (removed, excluded)
            # would otherwise never be visited again, leaving a stale
            # postponed marker in memory forever. Found by code review,
            # 2026-11-02.
            entity_ids = set(self._coordinator.cache) | set(self._pending) | set(self._postponed)
            self._dirty = False
            # Reset once per tick, under the same lock, see
            # self._announce_fire_count's own comment.
            self._announce_fire_count = 0
            await asyncio.gather(*(self._async_evaluate_one(entity_id, now) for entity_id in entity_ids))
            if self._dirty:
                await self._async_save()

    async def _async_min_ha_version(self, owner: str, repo: str, tag: str) -> str | None:
        """self._min_ha_version_cache's own read-through: a cache hit never
        touches the network, a miss fetches once (min_ha_version_fetch.py)
        and only remembers a *confirmed* answer (see that module's own
        docstring for what that means): a transient failure costs nothing
        more than trying again on the next tick, never a wrongly-permanent
        "no requirement found"."""
        key = (owner, repo, tag)
        if key in self._min_ha_version_cache:
            return self._min_ha_version_cache[key]
        access_token = await self._github_auth_manager.async_get_valid_access_token()
        confirmed, version = await async_fetch_min_ha_version(self.hass, owner, repo, tag, access_token)
        if confirmed:
            self._min_ha_version_cache[key] = version
        return version

    async def _async_evaluate_one(self, entity_id: str, now: datetime) -> None:
        # A previous "Update failed" notification has no business lingering
        # once the entity is genuinely installing again, however that retry
        # was triggered -- direct user feedback, 2026-08-11: it wasn't going
        # away on its own for a retry that didn't go through _async_execute
        # below (the only other place this used to get cleared), e.g. a
        # manual retry via Home Assistant's own native dialog, which this
        # integration can't see or pace at all (see README's own Known
        # limitations). Checked on every tick for every entity, ahead of the
        # early-return guards below, so it isn't skipped for an entity this
        # class itself currently has no opinion on (in_progress already
        # confirms a real install is underway; the dismiss itself is a
        # harmless no-op if there was nothing to clear).
        state = self.hass.states.get(entity_id)
        if state is not None and state.attributes.get("in_progress"):
            self._clear_failure_state(entity_id)

        if entity_id in self._recently_executed:
            # An install is still in flight for this entity (dispatched by
            # _async_execute, not yet resolved either way: cleared by
            # was_auto_installed on success or _async_run_install's own
            # except-branch on failure). Found by review: without this
            # guard, a slow install (e.g. a firmware flash) still running
            # at the next tick (the 5-minute timer, or any earlier
            # coordinator recompute) looked exactly like a fresh "ready"
            # update with nothing pending (this class's own _pending record
            # for it was already cleared, right at the start of
            # _async_execute, before dispatching), and got a second, fully
            # redundant announce+execute cycle stacked on top of the first
            # one still running.
            return

        if self._rollout_manager.is_queued(entity_id):
            # Found by review, 2026-07-22: a queued (not yet dispatched)
            # Zigbee rollout entry isn't in self._recently_executed (see
            # _async_execute's own "queued" branch, deliberately not set
            # until RolloutManager actually dispatches it, so
            # was_auto_installed() still attributes the real install
            # correctly whenever that turns out to be). Without this guard,
            # every subsequent tick sees no pending record either (already
            # cleared at the start of _async_execute) and treats it as a
            # brand-new, never-announced update, re-announcing it and
            # spawning a fresh persistent_notification with a new target
            # time every single announce cycle for as long as it sits
            # behind its sibling in the queue.
            return

        if self._rollout_manager.is_in_flight(entity_id):
            # Direct user feedback, 2026-11-08: a manually-dispatched
            # (Update All) Zigbee queue entry promoted to front the moment
            # its predecessor finished has is_auto=False, so it was never in
            # self._recently_executed above either -- is_queued() just
            # stopped protecting it (no longer waiting behind anyone), and
            # nothing else did, so it read as a brand-new, never-announced
            # update and got a fresh, spurious auto-install announce cycle
            # stacked on top of the manual install already running for it.
            # is_in_flight() covers this the same way regardless of
            # is_auto -- see its own docstring in rollout_manager.py.
            return

        cached = self._coordinator.cache.get(entity_id)
        current_to_version = cached["latest_version"] if cached else None

        postponed = self._postponed.get(entity_id)
        if postponed is not None:
            postponed_to_version, required_version = postponed
            if postponed_to_version != current_to_version:
                # A newer version appeared since the postponed one, no
                # reason to assume it has the same requirement, let it be
                # evaluated fresh below instead of carrying the old one's
                # postponed state over to it.
                del self._postponed[entity_id]
                self._dirty = True
            elif not ha_core_version_satisfies(HA_CORE_VERSION, required_version):
                # Self-healing: self._pending has no business holding an
                # entry here once genuinely postponed (async_mark_postponed
                # already clears it the moment it sets self._postponed, same
                # as _async_run_install's own except-branch relies on
                # _async_execute having already cleared it before
                # dispatching). Found live, 2026-11-04: an entity can still
                # have a stale self._pending entry left over from before
                # that was true, and nothing else ever clears it once this
                # early return starts firing every tick, since that only
                # happens inside _async_execute, which this never reaches
                # again while still postponed. Both are persisted, so it
                # survived several restarts too.
                if entity_id in self._pending:
                    del self._pending[entity_id]
                    self._dirty = True
                    self._refresh_pending_notification()
                return
            else:
                # Core itself now satisfies what this was waiting for.
                # Drop the postponed marker and fall straight through to a
                # perfectly normal evaluation below, same as any other
                # ready entity (direct user feedback, 2026-11-02: no
                # separate "resume" step, it should just behave normally
                # again). available_since is re-anchored to now, direct user
                # feedback, 2026-11-02: the staging wait period should start
                # once this is actually actionable, not have been counting
                # down invisibly the whole time it sat blocked, see
                # coordinator.py's own async_reset_available_since docstring.
                del self._postponed[entity_id]
                self._dirty = True
                await self._coordinator.async_reset_available_since(entity_id, postponed_to_version)

        # Proactive counterpart to the reactive check above: this release's
        # own hacs.json, fetched (and cached forever, see
        # self._min_ha_version_cache's own comment) straight from GitHub,
        # rather than waiting to discover the exact same requirement only
        # after a real install attempt fails. Runs whenever this entity
        # isn't already postponed above (either never was, or was just
        # cleared for a stale/now-satisfied version), deliberately before
        # any staging/schedule-wait logic below rather than only once
        # status reaches "ready", direct user feedback, 2026-11-04: the
        # staging wait period shouldn't start counting while an update
        # can't possibly be installed yet regardless, same reasoning
        # async_reset_available_since's own docstring already gives for why
        # that wait period gets re-anchored once a *reactive* postponement
        # resolves. Falls through to the normal flow below whenever this
        # can't find a requirement at all (no release_url, nothing parses,
        # no hacs.json, no "homeassistant" key), exactly as if this check
        # didn't exist.
        if cached and current_to_version:
            owner_repo_tag = parse_release_url(cached.get("release_url"))
            if owner_repo_tag is not None:
                # Not reusing required_version from the reactive branch
                # above: that one's a known-str tuple field, this one's a
                # fresh, possibly-unresolved lookup, different shapes for
                # mypy, not just a naming collision.
                proactive_required_version = await self._async_min_ha_version(*owner_repo_tag)
                if proactive_required_version is not None and not ha_core_version_satisfies(
                    HA_CORE_VERSION, proactive_required_version
                ):
                    self._postponed[entity_id] = (current_to_version, proactive_required_version)
                    self._dirty = True
                    if entity_id in self._pending:
                        del self._pending[entity_id]
                        self._refresh_pending_notification()
                    return

        # A stale cancellation (the entity has since moved to a different
        # target version) has no effect either way -- prune it so it
        # doesn't linger in storage forever.
        cancelled_entry = self._cancelled.get(entity_id)
        cancelled_to_version = cancelled_entry[0] if cancelled_entry is not None else None
        if cancelled_to_version is not None and cancelled_to_version != current_to_version:
            del self._cancelled[entity_id]
            cancelled_to_version = None
            self._dirty = True
        # Same pruning for the AI safety check's own non-cancelling result,
        # same "no longer the relevant version" reasoning. Not persisted
        # (see self._ai_check_results's own comment), so this doesn't set
        # self._dirty, same as self._failed/self._recently_announced never
        # do either.
        ai_check_entry = self._ai_check_results.get(entity_id)
        if ai_check_entry is not None and ai_check_entry[0] != current_to_version:
            del self._ai_check_results[entity_id]

        # cached["auto_install_excluded"] (coordinator.py's own
        # _is_excluded_from_auto_install) covers Core/Supervisor/HAOS too --
        # pre-populated default members of the same excluded_entities list
        # every other "always manual" entity lives in, not a separate
        # exception. The master pause switch is passed to decide_action as
        # its own, separate master_enabled argument, not folded in here --
        # see that function's own docstring for why (pausing freezes an
        # existing countdown in place instead of removing it).
        #
        # A trusted voter's own already-aggregated verdict for this exact
        # version (coordinator.py's own trusted_vote/trusted_voters_matched,
        # see community_verdict.py) can override both is_ready and the
        # size's own toggle below, and any problematic vote at all (from
        # anyone, not just a trusted voter -- coordinator.py's own
        # community_verdict.problematic_count) blocks eligibility outright
        # unless a trusted "healthy" override already applies -- see
        # effective_auto_install_state's own docstring for the full
        # reasoning (including why a "healthy" override still respects
        # auto_install_excluded and an explicit user skip).
        if cached:
            size_enabled = size_auto_install_enabled(cached["version_size"], self._rules)
            is_ready, rules_enabled, reason = effective_auto_install_state(
                status=cached["status"],
                size_enabled=size_enabled,
                auto_install_excluded=cached["auto_install_excluded"],
                trusted_vote=cached.get("trusted_vote"),
                community_problematic_count=(cached.get("community_verdict") or {}).get("problematic_count", 0),
                auto_install_whitelisted=cached.get("auto_install_whitelisted", False),
                native_auto_update=cached.get("native_auto_update", False),
            )
            trusted_voter_usernames = cached.get("trusted_voters_matched", []) if reason == "trusted_voter" else []
        else:
            is_ready, rules_enabled, reason, trusted_voter_usernames = False, False, None, []

        action = decide_action(
            is_ready=is_ready,
            auto_install_enabled=rules_enabled,
            master_enabled=self._coordinator.master_enabled,
            installable=bool(cached and cached["installable"]),
            existing=self._pending.get(entity_id),
            cancelled_to_version=cancelled_to_version,
            current_to_version=current_to_version,
            now=now,
            announce_wait=self._rules.announce_wait,
            # Reason is only ever "whitelist" when effective_auto_install_state
            # itself forced it (see that function's own auto_install_excluded/
            # skip precedence) -- reusing it here instead of re-reading
            # cached["auto_install_whitelisted"] a second time keeps this in
            # sync with whichever of the two actually decided eligibility.
            instant=reason == "whitelist",
            last_announced=self._recently_announced.get(entity_id),
        )

        # current_to_version is guaranteed non-None in both branches below:
        # decide_action only ever returns "announce"/"execute" once
        # is_ready was True, and is_ready only comes back True when cached
        # was truthy above (the else branch hardcodes it False), which is
        # exactly the one case current_to_version is a real string instead
        # of None.
        if action == "announce":
            assert current_to_version is not None
            await self._async_announce(entity_id, current_to_version, now)
        elif action == "execute":
            assert current_to_version is not None
            # reason is guaranteed non-None here: decide_action only ever
            # returns "execute" when auto_install_enabled was True, and
            # effective_auto_install_state never returns a True middle
            # value with a None reason (see its own docstring) -- the
            # fallback below is defensive, not expected to ever fire.
            await self._async_execute(entity_id, current_to_version, reason or "rules", trusted_voter_usernames)
        elif action == "remove":
            await self._async_remove(entity_id)

    async def _async_announce(self, entity_id: str, to_version: str, now: datetime) -> None:
        """Records the announcement (state + event), then rebuilds the one
        "Scheduled updates" notification from self._pending's own complete,
        current contents (see _refresh_pending_notification). `cached
        ["version_size"]` is read by the caller (for the size-based
        auto-install rules check, unrelated to this), not here:
        decide_action only ever returns "announce" when is_ready was True,
        which (see _async_evaluate_one's own is_ready branch) only happens
        when `cached` is truthy, so it's always available there without a
        None guard."""
        announcement = start_announcement(entity_id, to_version, now, self._rules.announce_wait)
        self._pending[entity_id] = announcement
        self._recently_announced[entity_id] = (to_version, now)
        self._dirty = True
        self._refresh_pending_notification()

        # See const.py's own EVENT_ANNOUNCED docstring for the events
        # design overall. from_version/release_url come from the
        # coordinator's cache, not the (possibly stale-by-now) update
        # entity's own state directly, same source install_log.py's own
        # entries already use for the same facts. release_url is already
        # corrected for Core (see corrected_release_url's own docstring),
        # so an automation reading it doesn't need to know that quirk
        # exists at all -- added so an automation can fetch the release
        # notes itself (directly, or via this integration's own
        # get_release_notes service, see services.py) before the install
        # actually runs, e.g. to run its own analysis and decide whether
        # to cancel it via cancel_scheduled_install.
        cached = self._coordinator.cache.get(entity_id)
        event_data = {
            "entity_id": entity_id,
            "from_version": cached.get("installed_version") if cached else None,
            "to_version": to_version,
            "release_url": cached.get("release_url") if cached else None,
            "execute_at": announcement.execute_at.isoformat(),
        }
        # Staggered, not fired the instant the state above is set, see
        # self._announce_fire_count's own comment. Only the event itself
        # is delayed; the pending state/notification just above already
        # reflect this announcement immediately, same as before. Dispatched
        # as its own background task, not awaited inline here: this method
        # runs inside _async_tick's own asyncio.gather, itself inside
        # self._lock (see that method's own comment on why that lock must
        # stay fast). An inline sleep here would hold that same lock for
        # the whole batch's stagger, reintroducing the exact "Save spins
        # for a long time" symptom that comment already fixed once. Found
        # by review, 2026-11-10, before this ever shipped.
        stagger_delay = self._announce_fire_count * _ANNOUNCE_FIRE_STAGGER_SECONDS
        self._announce_fire_count += 1
        if stagger_delay:
            self.hass.async_create_task(self._async_fire_announced_after_delay(stagger_delay, event_data))
        else:
            self._fire_announced(event_data)

    async def _async_fire_announced_after_delay(self, delay: float, event_data: dict[str, Any]) -> None:
        """The staggered half of _async_announce's own EVENT_ANNOUNCED fire,
        split into its own detached task so the delay never blocks
        _async_tick's own lock (see _async_announce's own comment)."""
        await asyncio.sleep(delay)
        self._fire_announced(event_data)

    def _fire_announced(self, event_data: dict[str, Any]) -> None:
        """Fires EVENT_ANNOUNCED itself, then, if an ai_task entity is
        configured, schedules the AI safety check for the exact same
        announcement, same window a person gets to cancel by hand
        (self._rules.announce_wait), on the theory the AI needs exactly
        that same window and no more. Scheduled as its own detached task,
        never awaited here: an ai_task call can take several seconds, and
        this runs from the same places _async_announce itself already
        can't block (see that method's own lock comment)."""
        self.hass.bus.async_fire(EVENT_ANNOUNCED, event_data)
        ai_task_entity_id = self._rules.ai_safety_check_entity_id
        if ai_task_entity_id and event_data["from_version"] is not None:
            self.hass.async_create_task(
                self._async_handle_ai_safety_check(
                    event_data["entity_id"], event_data["from_version"], event_data["to_version"], ai_task_entity_id
                )
            )

    async def _async_handle_ai_safety_check(
        self, entity_id: str, from_version: str, to_version: str, ai_task_entity_id: str
    ) -> None:
        """Runs the AI safety check and reacts to its verdict, scheduled
        by _fire_announced, never awaited inline there. A "blocked" verdict
        cancels the install exactly like a manual cancel does (same
        async_cancel), just with a reason attached; "passed"/"failed" are
        purely informational, kept only for the timeline's own "Passed the
        AI safety check"/"AI safety check failed" step (see
        self._ai_check_results's own comment).

        No deadline of its own tied to the announcement countdown, by
        design (same fail-open treatment a human who never got around to
        clicking Cancel in time already gets, nothing AI-specific here).
        But a "blocked" verdict that only comes back after to_version has
        already stopped being this entity's own live pending target (the
        countdown already elapsed and the install ran before the AI
        finished, or a newer update superseded it in the meantime) is
        skipped below instead of still calling async_cancel, found by code
        review: that call has no notion of "too late" on its own, so it
        would otherwise still record (and briefly show) a "Cancelled by AI
        safety check" result for a version that's already installed, before
        _async_evaluate_one's own next-tick pruning (self._cancelled's own
        comment) quietly removed it again."""
        result = await async_run_ai_safety_check(
            self.hass,
            entity_id=entity_id,
            update_name=_friendly_name(self.hass, entity_id),
            from_version=from_version,
            to_version=to_version,
            ai_task_entity_id=ai_task_entity_id,
        )
        if result.status != "blocked":
            self._ai_check_results[entity_id] = (
                to_version,
                result.status,
                result.reason,
                result.reason_code,
                result.notable,
            )
            return
        cached = self._coordinator.cache.get(entity_id)
        if cached is None or cached["latest_version"] != to_version:
            return
        await self.async_cancel(entity_id, to_version, reason=result.reason)

    @callback
    def _refresh_pending_notification(self) -> None:
        """Rebuilds the single "Scheduled updates" notification from
        self._pending's own complete, current contents, replacing whatever
        was there before rather than piling up a new one alongside it --
        direct user feedback, 2026-09-12: every previously separate
        notification (one per announcement, later one per same-tick batch)
        stuck around in the notifications list even once resolved, instead
        of ever being replaced. Dismissed entirely once nothing is left
        pending. Sorted by execute_at so the soonest one reads first,
        regardless of the order entities happened to be announced in.
        Also fires _listeners, the same trigger sensor.py's own
        UpdateManagerPendingInstallsSensor refreshes from."""
        self._fire_listeners()
        pending = sorted(self._pending.values(), key=lambda p: p.execute_at)
        if not pending:
            persistent_notification.async_dismiss(self.hass, _PENDING_NOTIFICATION_ID)
            return
        strings = localized_strings(self.hass, _NOTIFICATION_STRINGS)
        items = "\n".join(
            strings["item"].format(
                name=_friendly_name(self.hass, p.entity_id),
                to_version=p.to_version,
                when=dt_util.as_local(p.execute_at).strftime("%d-%m-%Y %H:%M"),
            )
            for p in pending
        )
        persistent_notification.async_create(
            self.hass,
            strings["body"].format(
                count=len(pending), plural="" if len(pending) == 1 else "s", items=items, url=_PANEL_UPDATES_URL
            ),
            title=strings["title"],
            notification_id=_PENDING_NOTIFICATION_ID,
        )

    async def _async_execute(
        self, entity_id: str, to_version: str, reason: AutoInstallReason, trusted_voter_usernames: list[str]
    ) -> None:
        # The pending announcement's own announced_at is read *before*
        # _async_remove clears it -- install_log.py wants this for the
        # History entry's own "Announced" fact, and it's gone from
        # self._pending the moment _async_remove runs below.
        pending = self._pending.get(entity_id)
        announced_at = pending.announced_at if pending is not None else None

        # Finalize the decision *before* dispatching the actual install
        # call: once the wait has elapsed, a cancel that arrives while the
        # install is being dispatched must have no effect (too late), not
        # race against this method to see which one touches self._pending
        # first -- found live: a cancel clicked in that exact window
        # cleared the pending record and dismissed the notification as if
        # cancelled, while the install had already been scheduled and
        # installed anyway.
        await self._async_remove(entity_id)

        service_data = install_service_data(self.hass, entity_id)

        # A no-op ("dispatch") for anything that isn't part of an active
        # multi-device Zigbee rollout, see rollout_manager.py's own
        # docstring. "queued" means a sibling device from the same network/
        # model/version is already installing right now; RolloutManager
        # will call update.install for this one itself once it's this
        # entity's turn (see its own _async_dispatch), and will call
        # mark_recently_executed below at that point so was_auto_installed()
        # still attributes it correctly, nothing further to do here.
        #
        # Wrapped in its own try/except, found by review: this call sits
        # inside _async_tick's own asyncio.gather with no
        # return_exceptions=True, so an unguarded exception here (e.g. a
        # Store I/O error inside RolloutManager) would otherwise abort the
        # whole tick before self._dirty state gets saved, and propagate to
        # whatever awaited _async_tick (e.g. a settings save). self._pending
        # was already cleared above, so simply logging and returning here
        # leaves the entity to be re-evaluated fresh next tick, same
        # natural retry _async_run_install's own except-branch already
        # relies on for the actual install call.
        context = AutoInstallContext(
            to_version=to_version,
            reason=reason,
            trusted_voter_usernames=trusted_voter_usernames,
            announced_at=announced_at,
        )
        try:
            result = await self._rollout_manager.async_request_install(
                entity_id, to_version, service_data, is_auto=True, context=context
            )
        except Exception:
            _LOGGER.exception("Update Manager couldn't check the rollout queue for %s", entity_id)
            return
        if result == "queued":
            return

        # Recorded before dispatching, not after it resolves (see
        # _async_run_install's own task) -- was_auto_installed() needs this
        # in place by the time coordinator.py's install-listener notices
        # installed_version actually changed, which can happen well before
        # the update.install call itself finishes.
        self._recently_executed[entity_id] = context
        # Its own task, not awaited inline: an install can take a while
        # (e.g. firmware download/flash), and one slow/failing entity
        # shouldn't hold up evaluating every other entity in the same tick.
        # blocking=True here (unlike the old blocking=False) so a genuine
        # install failure actually raises inside this task and gets logged
        # with our own context, instead of only ever surfacing as HA's
        # generic unhandled-task-exception log with no mention of
        # Update Manager at all.
        self.hass.async_create_task(self._async_run_install(entity_id, to_version, service_data))

    def mark_recently_executed(self, entity_id: str, context: AutoInstallContext) -> None:
        """Called by rollout_manager.py (via the setter it's given in
        __init__.py) when it dispatches a queued, auto-install-originated
        entry itself, once that entity's own turn in a Zigbee rollout
        finally comes: _async_execute above already does this directly
        for the immediately-dispatched (not queued at all) case; this
        covers the "was deferred, RolloutManager pressed the button later"
        case, so was_auto_installed() still attributes it correctly (and
        with the same reason/announced_at captured back when this was
        first requested, not whatever might apply *now*) either way."""
        self._recently_executed[entity_id] = context

    def was_auto_installed(self, entity_id: str, to_version: str) -> AutoInstallContext | None:
        """Consumed once by __init__.py's install-listener callback, fired
        when coordinator.py notices installed_version actually changed to
        `to_version` -- non-None only if *this* completed install was the
        one _async_execute just dispatched, not a manual click (or any
        other means) that happened to land on the same entity around the
        same time.

        Only pops the record on an actual match, not unconditionally --
        found live (well, found by review): a plain .pop(entity_id, None)
        discarded a still-valid record for a *different*, later dispatch
        whenever this fired first for some other, unrelated version change
        on the same entity (e.g. a manual install to an intermediate
        version landing before the real auto-installed one's own state
        change did) -- the genuine auto-install's own callback would then
        find no record left and misattribute it as a manual install in
        install_log.py.

        Also clears entity_id's failed/retrying state unconditionally
        (regardless of the match below): however this genuinely completed
        install came about, any earlier failure (or failure-driven retry
        countdown) recorded for it is stale now."""
        self._clear_failure_state(entity_id)
        context = self._recently_executed.get(entity_id)
        if context is None or context.to_version != to_version:
            return None
        del self._recently_executed[entity_id]
        return context

    async def async_dispatch_install(self, service_data: dict[str, Any], context: Context | None = None) -> None:
        """The actual update.install call, serialized via self._install_lock
        against every other HACS/Marketplace-backed install this exact
        class dispatches at the same time (see that field's own comment
        for the shared /tmp/hacs_backup-dir race this exists to prevent).
        Only a HACS-backed entity actually touches that shared directory,
        so only those contend for the lock; anything else (an add-on, a
        device's own firmware, Home Assistant Core/Supervisor/OS) is never
        held up by this at all, dispatched exactly as its own tier/rollout
        status already allows.

        Direct user feedback, 2026-11-14: a real "Update all" batch of
        ordinary add-ons and HACS integrations installed one at a time,
        every one of them waiting on the same global lock regardless of
        what it actually was, defeating the whole point of the tier gate's
        own "safe"-tier concurrency. This lock's own reach had quietly
        grown from "the two HACS installs that can actually race" to
        "literally every update this class ever dispatches" without
        anyone deciding that on purpose, confirmed against v0.17.0's own
        released source: the exact same lock-and-blocking-call shape.
        Public, not folded back into _async_run_install's own try block
        below, so websocket_api.py's manual-install path can route
        through this same, now correctly-scoped lock too.

        Also the one real funnel every install path (manual, auto, queued
        rollout) shares at all, exactly why this is also where the
        firmware-version-table submission for the version about to be left
        behind gets captured, right before the service call actually
        changes anything, then submitted as its own background task. See
        coordinator.py's own snapshot_firmware_version_submission_candidate
        for why the state read itself can't be part of that background
        task (found by code review: a detached task could run its own
        state read at any point during or after the install it was
        supposed to precede); a no-op for anything that isn't a Zigbee
        update entity, so unconditionally calling it here for every
        install costs nothing in practice.

        Being that one funnel is also why rollout_manager.py's own
        async_wait_for_backup_clear is awaited right here too, found live
        2026-11-25: a real "Update all" batch fired every entity's own
        dispatch at once, so each one's own earlier tier-gate check
        (async_request_install) already cleared before any of them had
        actually reached Home Assistant Core; none could have seen the
        backup the first one's install was about to trigger. This is the
        last point left in the whole dispatch path to catch that."""
        # nullcontext supports `async with` since Python 3.10 (bpo-41543),
        # well below HA Core's own much newer minimum -- found by /simplify:
        # the actual update.install call used to be written out twice here,
        # once under the lock and once not, with only the lock varying.
        entity_id = service_data.get("entity_id")
        if isinstance(entity_id, str):
            firmware_snapshot = self._coordinator.snapshot_firmware_version_submission_candidate(entity_id)
            if firmware_snapshot is not None:
                self.hass.async_create_task(
                    self._coordinator.async_submit_firmware_version_submission_candidate(entity_id, firmware_snapshot)
                )
            # One more backup-lock check, right here, right before the
            # call that actually matters. See
            # rollout_manager.py's own async_wait_for_backup_clear for why
            # the earlier tier-gate check alone isn't enough for a same-
            # instant batch like "Update all".
            await self._rollout_manager.async_wait_for_backup_clear(entity_id)
        lock = self._install_lock if isinstance(entity_id, str) and is_hacs_entity(self.hass, entity_id) else nullcontext()
        async with lock:
            await self.hass.services.async_call("update", "install", service_data, blocking=True, context=context)

    async def _async_run_install(self, entity_id: str, to_version: str, service_data: dict[str, Any]) -> None:
        try:
            await self.async_dispatch_install(service_data)
        except Exception as exception:
            required_version = min_ha_version_required(exception)
            if required_version is not None:
                # Deliberately quieter than the generic failure's own
                # _LOGGER.exception below: this is a known, recoverable
                # condition (see self._postponed's own comment), not
                # something actually wrong, and it'll keep rediscovering
                # the exact same thing on every tick until the user's own
                # HA Core version changes.
                _LOGGER.debug(
                    "Update Manager postponed %s: needs Home Assistant %s or newer",
                    entity_id,
                    required_version,
                )
                self._postponed[entity_id] = (to_version, required_version)
                self._dirty = True
                # Found by /code-review, 2026-11-03: without this, this
                # entity_id stayed in self._recently_executed forever (the
                # same bug _mark_failed's own matching clear below already
                # exists to prevent for a generic failure) -- _async_
                # evaluate_one's own in-flight guard then treated it as
                # permanently installing, so it was never re-evaluated
                # again, even once self._postponed resolved and HA Core
                # actually satisfied the requirement.
                self._release_recently_executed(entity_id, to_version)
                return
            reason = failure_reason_for(exception)
            if reason is not None:
                # Same "known, recoverable, not actually wrong" reasoning as
                # the min_ha_version_required branch above, for the other
                # labeled failure this project recognizes (Marketplace's own
                # one-time "accept the warning" gate, see
                # _MARKETPLACE_WARNING_NOT_ACCEPTED_KEY's own comment):
                # nothing here needs a developer's traceback, a plain fact
                # does the whole job.
                _LOGGER.debug("Update Manager's auto-install for %s failed: %s", entity_id, reason)
            else:
                _LOGGER.exception("Update Manager's auto-install failed for %s", entity_id)
            self.handle_install_failure(entity_id, to_version, reason=reason)

    def handle_install_failure(self, entity_id: str, to_version: str, *, reason: str | None = None) -> None:
        """Shared by _async_run_install's own except-branch above and
        rollout_manager.py (via the setter it's given in __init__.py, same
        pattern as set_recently_executed_setter): a queued entry's install
        is dispatched by RolloutManager itself once its turn comes, not by
        this class directly, so a failure there needs the exact same
        cleanup/notification, not a second, separately-maintained copy.
        Auto-install only -- see handle_manual_install_failure for the
        panel's own explicit Install button, which marks the same failure
        but never schedules a retry of its own (direct user feedback,
        2026-10-24: a deliberate, one-off click shouldn't silently turn
        into an ongoing automatic retry loop the user never asked for).

        `reason` (e.g. "warning_not_accepted", see failure_reason_for above)
        is purely for _refresh_failed_notification's own item text, unlike
        a required HA Core version (see self._postponed): there's nothing
        to check for cheaply before retrying, so this still goes through
        the exact same backoff schedule as a generic failure, just labeled
        more usefully."""
        if not self._mark_failed(entity_id, to_version, reason=reason):
            return

        # Escalating backoff (see _FAILURE_BACKOFF_SCHEDULE's own comment):
        # a fresh run of failures for this exact to_version starts back at
        # 1 -- a version change or a success already cleared any previous
        # count via _clear_failure_state above (called both by
        # was_auto_installed and by the already-installed short-circuit
        # inside _mark_failed).
        previous = self._failure_counts.get(entity_id)
        consecutive = previous[1] + 1 if previous is not None and previous[0] == to_version else 1
        self._failure_counts[entity_id] = (to_version, consecutive)
        delay = _FAILURE_BACKOFF_SCHEDULE[min(consecutive, len(_FAILURE_BACKOFF_SCHEDULE)) - 1]
        now = dt_util.utcnow()

        # The actual retry schedule: a perfectly normal PendingAnnouncement,
        # so the entire rest of the system (announcer.py's own decide_action,
        # the panel's badge/status/sort/dialog/Cancel) treats this exactly
        # like any other scheduled auto-install -- direct user feedback,
        # 2026-10-24, see this module's own top-of-file comment for the full
        # reasoning. announced_at is "now" (when this retry cycle started),
        # not the original announcement's own announced_at (already gone by
        # the time a failure is handled, cleared at the start of every
        # _async_execute attempt, including this one) -- a fresh, honest
        # fact ("retrying since") rather than a stale, harder-to-get-right
        # one.
        self._pending[entity_id] = PendingAnnouncement(
            entity_id=entity_id, to_version=to_version, announced_at=now, execute_at=now + delay
        )
        self._dirty = True
        self._refresh_pending_notification()

    async def async_mark_postponed(self, entity_id: str, to_version: str, required_version: str) -> None:
        """websocket_api.py's own _async_run_manual_install calls this when
        a manual Install click hits the exact same "needs a newer HA Core
        version" failure _async_run_install's own except-branch already
        parks in self._postponed. Direct user feedback, 2026-11-02: the
        fact that a given to_version needs a newer HA Core is true
        regardless of which path discovered it, so a manual click learning
        it should update the same shared state, not just show a one-off
        "Failed updates" message and leave auto-install to rediscover the
        exact same thing on its own, later schedule. Saved immediately
        (like async_cancel above), not left to self._dirty and whatever
        _async_tick's own batched save happens to catch next.

        Also clears any existing self._pending announcement for this
        entity. Found live, 2026-11-02: unlike _async_run_install's own
        except-branch (reached only after _async_execute already cleared
        self._pending for this entity_id, right before dispatching), this
        method can be reached with a real, still-active announcement still
        in place (e.g. auto-install already scheduled this same update for
        tomorrow when the manual click happened), showing a contradictory
        "will auto-install tomorrow" step alongside "Postponed" in the
        detail dialog otherwise."""
        self._postponed[entity_id] = (to_version, required_version)
        if entity_id in self._pending:
            del self._pending[entity_id]
            self._refresh_pending_notification()
        await self._async_save()

    def handle_manual_install_failure(self, entity_id: str, to_version: str, *, reason: str | None = None) -> None:
        """websocket_api.py's own _handle_install (the panel's explicit
        Install/Install all button) dispatches update.install the exact
        same fire-and-forget way _async_run_install does, but never used to
        catch a failure there at all -- found live, 2026-10-24, right after
        shipping handle_install_failure's own backoff/notification above: a
        manual click got *less* failure visibility than an automatic retry
        now does, the wrong way around. Marks the same "Failed updates"
        notification, but deliberately doesn't call into
        handle_install_failure's own backoff (see that method's own
        docstring for why)."""
        self._mark_failed(entity_id, to_version, reason=reason)

    def _release_recently_executed(self, entity_id: str, to_version: str) -> None:
        """Clears self._recently_executed for entity_id once an auto-install
        attempt has resolved without installed_version actually changing
        (a real failure, or a postponement). was_auto_installed is the
        only *other* place that clears it, and it's never called if
        installed_version never actually changes, so this stays recorded
        forever otherwise. Also, since _async_evaluate_one treats any
        entity_id still in self._recently_executed as "install in flight",
        leaving this in place would permanently freeze the entity out of
        ever being re-announced, even once self._postponed resolves or a
        later attempt would otherwise succeed. A no-op for a queued entry
        (or a manual install) that was never auto-install's own doing in
        the first place (never set in self._recently_executed to begin
        with), or for a stale record left by some other, unrelated
        dispatch for a different to_version."""
        context = self._recently_executed.get(entity_id)
        if context is not None and context.to_version == to_version:
            del self._recently_executed[entity_id]

    def _mark_failed(
        self, entity_id: str, to_version: str, *, reason: str | None = None
    ) -> bool:
        """Shared by handle_install_failure (auto) and
        handle_manual_install_failure (manual) above: records the failure
        in the shared "Failed updates" notification and fires
        EVENT_INSTALL_FAILED, regardless of which path triggered it. No
        Repair issue -- direct user feedback, 2026-10-24: redundant next to
        this same, already-visible notification, especially for something
        that (unlike rollout_manager.py's own stuck-install issue) has no
        real "fix" action of its own besides the retry that's already
        happening on its own.

        Deliberately never reached for a too-old-HA-Core postponement
        (async_mark_postponed/the three _async_run_install-style except-
        branches that set self._postponed go their own, separate way
        entirely, never calling this). Considered and rejected firing
        EVENT_INSTALL_FAILED there too, code review, 2026-11-03: a
        postponement is already treated as a known, recoverable condition
        throughout this feature (debug logging instead of a traceback, no
        "Failed updates" entry, no backoff retry), not a real failure, so
        an "Install failed" automation firing for it would contradict that
        same, deliberate framing everywhere else.

        Returns False (and does nothing else) when the install actually
        succeeded despite whatever raised this -- direct user feedback,
        2026-09-30, after a tier-gated Core/OS install genuinely completed
        but still produced a "couldn't install" notification (a stale,
        pre-restart tier-gate entry got redispatched against an entity that
        already had nothing left to install, see rollout_manager.py's own
        _async_dispatch/_async_retry_tier_blocked comments for the actual
        bug that's now fixed at the source). Checked here, not just there,
        as a second, more general safety net: whatever the caller, and
        however it happened, an entity already sitting on the version this
        failure is about never needs a failure notification (or a
        backoff retry) for it.

        `reason` (currently only ever "warning_not_accepted": the other
        labeled failure reason, a too-old HA Core, now goes through
        async_mark_postponed instead, see that method's own docstring)
        only changes _refresh_failed_notification's own item text for this
        entity, see that method's own comment."""
        self._release_recently_executed(entity_id, to_version)

        state = self.hass.states.get(entity_id)
        if state is not None and state.attributes.get("installed_version") == to_version:
            self._clear_failure_state(entity_id)
            return False

        self._failed[entity_id] = (to_version, reason)
        self._refresh_failed_notification()
        # See const.py's own EVENT_ANNOUNCED docstring for the events
        # design overall.
        self.hass.bus.async_fire(EVENT_INSTALL_FAILED, {"entity_id": entity_id, "to_version": to_version})
        return True

    async def _async_remove(self, entity_id: str) -> None:
        # Also called at the start of every _async_execute, i.e. right
        # before each (re)attempt. Fully delegated to _clear_failure_state:
        # "no announcement applies anymore" and "no failed/retrying state
        # applies anymore" are the exact same situation now that a failure-
        # driven retry (handle_install_failure below) is itself just a
        # PendingAnnouncement in self._pending -- see that method's own
        # comment for why this used to be two separate concepts and no
        # longer needs to be.
        self._clear_failure_state(entity_id)

    @callback
    def _clear_failure_state(self, entity_id: str) -> None:
        """Fully resets entity_id's failed/retrying state: any pending
        announcement (a normal countdown, or a failure-driven retry --
        indistinguishable here on purpose, see handle_install_failure),
        the shared "Failed updates" notification entry, and the
        consecutive-failure count driving the backoff schedule. Every call
        site here means "this entity's failed/pending state no longer
        applies" (a genuinely fresh attempt starting, a success, or this
        entity no longer being our concern at all), which is exactly when
        any of these would otherwise linger."""
        if entity_id in self._pending:
            del self._pending[entity_id]
            self._dirty = True
            self._refresh_pending_notification()
        if self._failed.pop(entity_id, None) is not None:
            self._refresh_failed_notification()
        self._failure_counts.pop(entity_id, None)
        if self._postponed.pop(entity_id, None) is not None:
            self._dirty = True

    @callback
    def _refresh_failed_notification(self) -> None:
        """Rebuilds the single "Failed updates" notification from
        self._failed's own complete, current contents, same
        one-notification-total reasoning as _refresh_pending_notification.
        Dismissed entirely once nothing is left failed. An entity with a
        recognized reason tag (see _mark_failed) gets a specific item
        template (e.g. "item_warning_not_accepted") instead of the generic
        one, same strings dict, just a different key, falling back to
        "item" for anything unrecognized or unset. Also fires _listeners,
        the same trigger sensor.py's own UpdateManagerFailedInstallsSensor
        refreshes from."""
        self._fire_listeners()
        if not self._failed:
            persistent_notification.async_dismiss(self.hass, _FAILED_NOTIFICATION_ID)
            return
        strings = localized_strings(self.hass, _FAILED_NOTIFICATION_STRINGS)
        items = "\n".join(
            strings.get(f"item_{reason}", strings["item"]).format(
                name=_friendly_name(self.hass, entity_id), to_version=to_version
            )
            for entity_id, (to_version, reason) in self._failed.items()
        )
        persistent_notification.async_create(
            self.hass,
            strings["body"].format(
                count=len(self._failed), plural="" if len(self._failed) == 1 else "s", items=items, url=_PANEL_UPDATES_URL
            ),
            title=strings["title"],
            notification_id=_FAILED_NOTIFICATION_ID,
        )
