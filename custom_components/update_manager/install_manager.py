"""Wires announcer.py's pure decisions into real behaviour: persists pending
auto-install announcements (Store, survives restarts), runs a periodic
check, actually calls `update.install` (with `backup=True` when the entity
supports it) once an announcement's wait elapses uncancelled, and shows/
clears a `persistent_notification` -- deliberately not a Repair issue, see
FUTURE.md's "Auto-install (niveau 3)" note: this isn't a problem to fix,
just an announcement.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.components.update import UpdateEntityFeature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .announcer import (
    AutoInstallRules,
    PendingAnnouncement,
    decide_action,
    size_auto_install_enabled,
    start_announcement,
)
from .const import (
    CONF_ANNOUNCE_HOURS,
    CONF_BIG_AUTO_INSTALL,
    CONF_MEDIUM_AUTO_INSTALL,
    CONF_SMALL_AUTO_INSTALL,
    DEFAULT_ANNOUNCE_HOURS,
    DOMAIN,
)
from .coordinator import UpdateManagerCoordinator

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_pending_installs"

_CHECK_INTERVAL = timedelta(minutes=5)
_NOTIFICATION_ID_PREFIX = f"{DOMAIN}_pending_install_"
_PANEL_UPDATES_URL = "/update-manager/updates"

# hass.config.language-driven, same convention the panel's own TRANSLATIONS
# already uses (see update-manager-panel.js) -- found live there: a user with
# hass.language "en" still saw all-Dutch panel text before that was fixed,
# and this persistent_notification (the one place Update Manager announces
# a pending auto-install outside the panel) had the same bug.
_NOTIFICATION_STRINGS = {
    "en": {
        "title": "Scheduled update",
        "body": (
            "Update Manager wants to update **{name}** to version {to_version} on {when}. "
            "If you don't want that, cancel it on the [Update Manager page]({url})."
        ),
    },
    "nl": {
        "title": "Geplande update",
        "body": (
            "Update Manager wil **{name}** bijwerken naar versie {to_version} op {when}. "
            "Wil je dat niet, annuleer dan op de [Update Manager-pagina]({url})."
        ),
    },
}

_FAILURE_NOTIFICATION_ID_PREFIX = f"{DOMAIN}_failed_install_"

# Same hass.config.language convention as _NOTIFICATION_STRINGS above.
# Direct user feedback: a failed auto-install used to only ever show up as
# an exception in the log, with nothing telling the user it happened at
# all, let alone in their own language.
_FAILURE_NOTIFICATION_STRINGS = {
    "en": {
        "title": "Update failed",
        "body": (
            "Update Manager tried to update **{name}** to version {to_version}, but the install "
            "failed. Check the Home Assistant logs for details, or try installing it manually from "
            "the [Update Manager page]({url})."
        ),
    },
    "nl": {
        "title": "Update mislukt",
        "body": (
            "Update Manager probeerde **{name}** bij te werken naar versie {to_version}, maar de "
            "installatie is mislukt. Bekijk de Home Assistant-logs voor details, of installeer "
            "handmatig via de [Update Manager-pagina]({url})."
        ),
    },
}


def auto_install_rules_from_options(options: dict) -> AutoInstallRules:
    return AutoInstallRules(
        small_auto_install=bool(options.get(CONF_SMALL_AUTO_INSTALL, False)),
        medium_auto_install=bool(options.get(CONF_MEDIUM_AUTO_INSTALL, False)),
        big_auto_install=bool(options.get(CONF_BIG_AUTO_INSTALL, False)),
        announce_wait=timedelta(hours=options.get(CONF_ANNOUNCE_HOURS, DEFAULT_ANNOUNCE_HOURS)),
    )


def _friendly_name(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    return state.name if state else entity_id


class InstallManager:
    def __init__(self, hass: HomeAssistant, coordinator: UpdateManagerCoordinator, rules: AutoInstallRules) -> None:
        self.hass = hass
        self._coordinator = coordinator
        self._rules = rules
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._pending: dict[str, PendingAnnouncement] = {}
        # entity_id -> the to_version the user explicitly cancelled -- stays
        # quiet for that exact target, a newer version is free to announce.
        self._cancelled: dict[str, str] = {}
        # Set by _async_announce/_async_remove/the stale-cancellation prune
        # during a tick, so _async_tick can save once at the end instead of
        # once per changed entity -- see _async_tick's own comment.
        self._dirty = False
        self._unsub_timer = None
        self._unsub_coordinator_listener = None
        # entity_id -> the to_version _async_execute just dispatched
        # update.install for -- lets __init__.py's install-listener (fired
        # once the entity's installed_version actually changes, from
        # coordinator.py) tell install_log.py whether *this* completed
        # install was auto-install's doing or a manual click elsewhere.
        # Not persisted: only meaningful for the brief window between
        # dispatching and the entity's own state catching up.
        self._recently_executed: dict[str, str] = {}
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
        self._cancelled = dict(data.get("cancelled", {}))

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
                "cancelled": self._cancelled,
            }
        )

    def pending_for(self, entity_id: str) -> PendingAnnouncement | None:
        return self._pending.get(entity_id)

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

    async def async_cancel(self, entity_id: str, to_version: str) -> None:
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
        not exist yet."""
        self._cancelled[entity_id] = to_version
        await self._async_remove(entity_id)
        await self._async_save()

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
            entity_ids = set(self._coordinator.cache) | set(self._pending)
            self._dirty = False
            await asyncio.gather(*(self._async_evaluate_one(entity_id, now) for entity_id in entity_ids))
            if self._dirty:
                await self._async_save()

    async def _async_evaluate_one(self, entity_id: str, now: datetime) -> None:
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

        cached = self._coordinator.cache.get(entity_id)
        current_to_version = cached["latest_version"] if cached else None

        # A stale cancellation (the entity has since moved to a different
        # target version) has no effect either way -- prune it so it
        # doesn't linger in storage forever.
        cancelled_to_version = self._cancelled.get(entity_id)
        if cancelled_to_version is not None and cancelled_to_version != current_to_version:
            del self._cancelled[entity_id]
            cancelled_to_version = None
            self._dirty = True

        # Core/Supervisor/HAOS: hard, non-configurable exception -- never
        # auto-install these regardless of the size/setting, see
        # coordinator.py's _is_hard_excluded_from_auto_install. The master
        # pause switch is passed to decide_action as its own, separate
        # master_enabled argument, not folded in here -- see that
        # function's own docstring for why (pausing freezes an existing
        # countdown in place instead of removing it).
        rules_enabled = (
            size_auto_install_enabled(cached["version_size"], self._rules)
            if cached and not cached["auto_install_excluded"]
            else False
        )
        action = decide_action(
            is_ready=bool(cached and cached["status"] == "ready"),
            auto_install_enabled=rules_enabled,
            master_enabled=self._coordinator.master_enabled,
            installable=bool(cached and cached["installable"]),
            existing=self._pending.get(entity_id),
            cancelled_to_version=cancelled_to_version,
            current_to_version=current_to_version,
            now=now,
            announce_wait=self._rules.announce_wait,
        )

        if action == "announce":
            await self._async_announce(entity_id, current_to_version, now)
        elif action == "execute":
            await self._async_execute(entity_id, current_to_version)
        elif action == "remove":
            await self._async_remove(entity_id)

    async def _async_announce(self, entity_id: str, to_version: str, now: datetime) -> None:
        announcement = start_announcement(entity_id, to_version, now, self._rules.announce_wait)
        self._pending[entity_id] = announcement
        self._dirty = True

        name = _friendly_name(self.hass, entity_id)
        when = dt_util.as_local(announcement.execute_at).strftime("%d-%m-%Y %H:%M")
        strings = _NOTIFICATION_STRINGS.get(self.hass.config.language, _NOTIFICATION_STRINGS["en"])
        persistent_notification.async_create(
            self.hass,
            strings["body"].format(name=name, to_version=to_version, when=when, url=_PANEL_UPDATES_URL),
            title=strings["title"],
            notification_id=f"{_NOTIFICATION_ID_PREFIX}{entity_id}",
        )

    async def _async_execute(self, entity_id: str, to_version: str) -> None:
        # Finalize the decision *before* dispatching the actual install
        # call: once the wait has elapsed, a cancel that arrives while the
        # install is being dispatched must have no effect (too late), not
        # race against this method to see which one touches self._pending
        # first -- found live: a cancel clicked in that exact window
        # cleared the pending record and dismissed the notification as if
        # cancelled, while the install had already been scheduled and
        # installed anyway.
        await self._async_remove(entity_id)

        # Recorded before dispatching, not after it resolves (see
        # _async_run_install's own task) -- was_auto_installed() needs this
        # in place by the time coordinator.py's install-listener notices
        # installed_version actually changed, which can happen well before
        # the update.install call itself finishes.
        self._recently_executed[entity_id] = to_version

        state = self.hass.states.get(entity_id)
        supported_features = state.attributes.get("supported_features", 0) if state else 0
        service_data: dict[str, Any] = {"entity_id": entity_id}
        if supported_features & UpdateEntityFeature.BACKUP:
            service_data["backup"] = True
        # Its own task, not awaited inline: an install can take a while
        # (e.g. firmware download/flash), and one slow/failing entity
        # shouldn't hold up evaluating every other entity in the same tick.
        # blocking=True here (unlike the old blocking=False) so a genuine
        # install failure actually raises inside this task and gets logged
        # with our own context, instead of only ever surfacing as HA's
        # generic unhandled-task-exception log with no mention of
        # Update Manager at all.
        self.hass.async_create_task(self._async_run_install(entity_id, to_version, service_data))

    def was_auto_installed(self, entity_id: str, to_version: str) -> bool:
        """Consumed once by __init__.py's install-listener callback, fired
        when coordinator.py notices installed_version actually changed to
        `to_version` -- True only if *this* completed install was the one
        _async_execute just dispatched, not a manual click (or any other
        means) that happened to land on the same entity around the same
        time.

        Only pops the record on an actual match, not unconditionally --
        found live (well, found by review): a plain .pop(entity_id, None)
        discarded a still-valid record for a *different*, later dispatch
        whenever this fired first for some other, unrelated version change
        on the same entity (e.g. a manual install to an intermediate
        version landing before the real auto-installed one's own state
        change did) -- the genuine auto-install's own callback would then
        find no record left and misattribute it as a manual install in
        install_log.py."""
        if self._recently_executed.get(entity_id) != to_version:
            return False
        del self._recently_executed[entity_id]
        return True

    async def _async_run_install(self, entity_id: str, to_version: str, service_data: dict[str, Any]) -> None:
        try:
            await self.hass.services.async_call("update", "install", service_data, blocking=True)
        except Exception:
            _LOGGER.exception("Update Manager's auto-install failed for %s", entity_id)
            # Otherwise this stays recorded forever (was_auto_installed is
            # the only other place that clears it, and it's never called if
            # installed_version never actually changes) -- a later, wholly
            # unrelated install of this entity to the exact same to_version
            # (a manual retry, say) would then be wrongly attributed to us.
            # Also, since _async_evaluate_one now treats any entity_id
            # still in self._recently_executed as "install in flight" (see
            # its own comment), leaving this in place after a real failure
            # would permanently freeze the entity out of ever being
            # re-announced.
            if self._recently_executed.get(entity_id) == to_version:
                del self._recently_executed[entity_id]

            name = _friendly_name(self.hass, entity_id)
            strings = _FAILURE_NOTIFICATION_STRINGS.get(self.hass.config.language, _FAILURE_NOTIFICATION_STRINGS["en"])
            persistent_notification.async_create(
                self.hass,
                strings["body"].format(name=name, to_version=to_version, url=_PANEL_UPDATES_URL),
                title=strings["title"],
                notification_id=f"{_FAILURE_NOTIFICATION_ID_PREFIX}{entity_id}",
            )

    async def _async_remove(self, entity_id: str) -> None:
        if entity_id in self._pending:
            del self._pending[entity_id]
            self._dirty = True
        persistent_notification.async_dismiss(self.hass, f"{_NOTIFICATION_ID_PREFIX}{entity_id}")
        # Also called at the start of every _async_execute, i.e. right
        # before each (re)attempt: clears out a previous attempt's
        # failure notification so it doesn't linger once a retry is
        # actually underway.
        persistent_notification.async_dismiss(self.hass, f"{_FAILURE_NOTIFICATION_ID_PREFIX}{entity_id}")
