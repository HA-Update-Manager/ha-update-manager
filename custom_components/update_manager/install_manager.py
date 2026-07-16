"""Wires announcer.py's pure decisions into real behaviour: persists pending
auto-install announcements (Store, survives restarts), runs a periodic
check, actually calls `update.install` (with `backup=True` when the entity
supports it) once an announcement's wait elapses uncancelled, and shows/
clears a `persistent_notification` -- deliberately not a Repair issue, see
FUTURE.md's "Auto-install (niveau 3)" note: this isn't a problem to fix,
just an announcement.
"""
from __future__ import annotations

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

    def update_rules(self, rules: AutoInstallRules) -> None:
        """Applies newly-saved auto-install rules in place -- no reload
        needed, see coordinator.py's async_update_rules for the same
        reasoning. The next periodic tick (at most 5 minutes away) picks
        this up naturally."""
        self._rules = rules

    @callback
    def async_stop(self) -> None:
        if self._unsub_timer is not None:
            self._unsub_timer()
            self._unsub_timer = None

    async def async_cancel(self, entity_id: str) -> None:
        pending = self._pending.get(entity_id)
        if pending is None:
            return
        self._cancelled[entity_id] = pending.to_version
        await self._async_remove(entity_id)
        await self._async_save()

    async def _async_tick(self, now: datetime) -> None:
        # Every entity the coordinator currently tracks, plus any entity
        # with a leftover announcement that isn't in the cache at all
        # anymore (e.g. the update disappeared) -- the latter defaults to
        # "not ready", so decide_action correctly cleans it up.
        #
        # One save at the end of the loop, not one per entity that changed
        # (_async_announce/_async_remove/the stale-cancellation prune below
        # just mark self._dirty) -- Store.async_save writes the whole
        # pending+cancelled dict immediately, so saving per-entity inside a
        # loop of N changed entities was N full-file writes of an O(N)
        # payload in the same tick instead of one.
        entity_ids = set(self._coordinator.cache) | set(self._pending)
        self._dirty = False
        for entity_id in entity_ids:
            await self._async_evaluate_one(entity_id, now)
        if self._dirty:
            await self._async_save()

    async def _async_evaluate_one(self, entity_id: str, now: datetime) -> None:
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
        # coordinator.py's _is_hard_excluded_from_auto_install.
        enabled = (
            size_auto_install_enabled(cached["version_size"], self._rules)
            if cached and not cached["auto_install_excluded"]
            else False
        )
        remaining = (
            timedelta(seconds=cached["remaining_seconds"])
            if cached and cached["remaining_seconds"] is not None
            else None
        )
        action = decide_action(
            is_ready=bool(cached and cached["status"] == "ready"),
            remaining=remaining,
            auto_install_enabled=enabled,
            installable=bool(cached and cached["installable"]),
            existing=self._pending.get(entity_id),
            cancelled_to_version=cancelled_to_version,
            current_to_version=current_to_version,
            now=now,
            announce_wait=self._rules.announce_wait,
        )

        if action == "announce":
            await self._async_announce(entity_id, current_to_version, now, remaining)
        elif action == "execute":
            await self._async_execute(entity_id)
        elif action == "remove":
            await self._async_remove(entity_id)

    async def _async_announce(
        self, entity_id: str, to_version: str, now: datetime, remaining: timedelta | None
    ) -> None:
        announcement = start_announcement(entity_id, to_version, now, self._rules.announce_wait, remaining)
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

    async def _async_execute(self, entity_id: str) -> None:
        # Finalize the decision *before* dispatching the actual install
        # call: once the wait has elapsed, a cancel that arrives while the
        # install is being dispatched must have no effect (too late), not
        # race against this method to see which one touches self._pending
        # first -- found live: a cancel clicked in that exact window
        # cleared the pending record and dismissed the notification as if
        # cancelled, while the install had already been scheduled and
        # installed anyway.
        await self._async_remove(entity_id)

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
        self.hass.async_create_task(self._async_run_install(entity_id, service_data))

    async def _async_run_install(self, entity_id: str, service_data: dict[str, Any]) -> None:
        try:
            await self.hass.services.async_call("update", "install", service_data, blocking=True)
        except Exception:
            _LOGGER.exception("Update Manager's auto-install failed for %s", entity_id)

    async def _async_remove(self, entity_id: str) -> None:
        if entity_id in self._pending:
            del self._pending[entity_id]
            self._dirty = True
        persistent_notification.async_dismiss(self.hass, f"{_NOTIFICATION_ID_PREFIX}{entity_id}")
