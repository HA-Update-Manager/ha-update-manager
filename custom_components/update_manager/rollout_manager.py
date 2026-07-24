"""Paces firmware installs across Zigbee devices sharing the same network,
model, and target version, one device at a time, not all at once (real
radio traffic that can destabilize the mesh otherwise). See zigbee.py for
how a device is recognized as Zigbee at all and which network it belongs to.

The pacing itself is rollout.py's own pure, already-tested queue logic
(build_queue/next_ready_device/mark_installed); this module is exactly the
"homeassistant-side wiring" that module's own docstring says isn't built
yet: grouping real devices via the device registry, triggering the real
`update.install` call once a device's turn comes, and persisting the queue
across restarts. In practice this reimplements rollout.py's own FIFO/
wait-between-installs decision directly on the entries list below rather
than constructing a `rollout.RolloutQueue` object each time, since the wait
here is always zero (see this module's own docstring further down) and the
entries already need their own richer per-request bookkeeping (service_data,
whether the request was auto-install's doing) that RolloutEntry doesn't carry.

Deliberately narrow in scope (2026-07-22 design discussion): only Zigbee
devices are paced at all, the wait between devices is not a fixed duration,
strictly "the previous one is confirmed complete, now the next one may
go", and a queue only exists reactively, once a second device from the
same group has actually been asked to install while one is already in
flight. A lone device, or the first device asked to install from a group,
always installs immediately; nothing here changes for the overwhelmingly
common non-Zigbee case.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any, Literal

from homeassistant.core import HomeAssistant, State, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .announcer import AutoInstallContext
from .const import DOMAIN
from .coordinator import UpdateManagerCoordinator
from .zigbee import device_for_entity, zigbee_network_id

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_rollout_queues"

RequestResult = Literal["dispatch", "queued"]


def _serialize_context(context: AutoInstallContext | None) -> dict[str, Any] | None:
    if context is None:
        return None
    return {
        "to_version": context.to_version,
        "reason": context.reason,
        "trusted_voter_usernames": context.trusted_voter_usernames,
        "announced_at": context.announced_at.isoformat() if context.announced_at is not None else None,
    }


def _deserialize_context(data: dict[str, Any] | None) -> AutoInstallContext | None:
    if data is None:
        return None
    return AutoInstallContext(
        to_version=data["to_version"],
        reason=data["reason"],
        trusted_voter_usernames=data.get("trusted_voter_usernames", []),
        announced_at=dt_util.parse_datetime(data["announced_at"]) if data.get("announced_at") else None,
    )


class _QueuedEntry:
    __slots__ = ("entity_id", "to_version", "service_data", "is_auto", "context")

    def __init__(
        self,
        entity_id: str,
        to_version: str,
        service_data: dict[str, Any],
        is_auto: bool,
        context: AutoInstallContext | None = None,
    ) -> None:
        self.entity_id = entity_id
        self.to_version = to_version
        self.service_data = service_data
        # Only auto-install's own requests should end up marked as
        # "auto_installed" in install_log.py once this module is the one
        # that actually dispatches them later (see _async_dispatch):
        # a manually-triggered request (the dialog's Install button, or
        # Update All) that happens to get queued behind another device must
        # never be misattributed as automatic just because this module was
        # the one that eventually pressed the button for it.
        self.is_auto = is_auto
        # Only ever set (and meaningful) when is_auto is True -- the exact
        # reason/timing install_manager.py's own _async_execute already
        # captured when this was first requested, carried along so
        # _async_dispatch can attribute it correctly whenever this entry's
        # own turn in the queue actually comes, possibly much later.
        self.context = context


class RolloutManager:
    def __init__(self, hass: HomeAssistant, coordinator: UpdateManagerCoordinator) -> None:
        self.hass = hass
        self._coordinator = coordinator
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        # group_key -> ordered list of not-yet-confirmed-complete entries.
        # The first entry in each list is the one currently dispatched
        # (in flight); the rest are still waiting their turn. A group with
        # no entry here at all simply doesn't exist yet (see this module's
        # own docstring: reactive, not built proactively).
        self._queues: dict[str, list[_QueuedEntry]] = {}
        # Told about by __init__.py so a queue-dispatched auto-install still
        # gets correctly attributed in install_log.py, see
        # set_recently_executed_setter's own docstring.
        self._mark_recently_executed: Callable[[str, AutoInstallContext], None] | None = None
        # Same reasoning/wiring as _mark_recently_executed above, see
        # set_failure_handler's own docstring: a queued entry's install can
        # fail too, once this module is the one dispatching it.
        self._handle_install_failure: Callable[[str, str], None] | None = None
        self._unsub_install_listener: Callable[[], None] | None = None

    def set_recently_executed_setter(self, setter: Callable[[str, AutoInstallContext], None]) -> None:
        """install_manager.py's own _recently_executed dict is what
        was_auto_installed()/__init__.py's _on_install use to tell "this
        completed install was auto-install's doing" apart from a manual
        click, when THIS module is the one that actually dispatches an
        auto-install-originated queued entry (not install_manager.py's own
        _async_execute directly, which already sets this for the first,
        immediately-dispatched entry in a group), it needs to set that same
        record itself, through this setter, rather than duplicating
        install_manager.py's own bookkeeping or importing it directly (which
        would create an import cycle, since install_manager.py is the one
        that calls into this module first)."""
        self._mark_recently_executed = setter

    def set_failure_handler(self, handler: Callable[[str, str], None]) -> None:
        """install_manager.py's own handle_install_failure does the exact
        cleanup/notification a failed install already needs (see
        _async_run_install's own except-branch): found by review, a queued
        entry's install (dispatched by this module, not install_manager.py's
        own _async_execute) had no failure path at all before this. Same
        setter pattern, same import-cycle reasoning, as
        set_recently_executed_setter above."""
        self._handle_install_failure = handler

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self._queues = {
            group_key: [
                _QueuedEntry(
                    e["entity_id"], e["to_version"], e["service_data"], e["is_auto"], _deserialize_context(e.get("context"))
                )
                for e in entries
            ]
            for group_key, entries in data.items()
        }

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                group_key: [
                    {
                        "entity_id": e.entity_id,
                        "to_version": e.to_version,
                        "service_data": e.service_data,
                        "is_auto": e.is_auto,
                        "context": _serialize_context(e.context),
                    }
                    for e in entries
                ]
                for group_key, entries in self._queues.items()
            }
        )

    def async_start(self) -> None:
        self._unsub_install_listener = self._coordinator.async_add_install_listener(self._on_install_completed)
        # Restart recovery: for every persisted queue, check whether its
        # front entry actually finished (or is still genuinely mid-install):
        # neither can just be assumed after a restart, since no task or
        # callback survives one. See _async_recover_after_restart's own
        # docstring.
        self.hass.async_create_task(self._async_recover_after_restart())

    @callback
    def async_stop(self) -> None:
        if self._unsub_install_listener is not None:
            self._unsub_install_listener()
            self._unsub_install_listener = None

    def _group_key_for(self, entity_id: str, to_version: str) -> str | None:
        """None if this entity isn't a Zigbee device at all (or its device
        can't be resolved), meaning it's never paced, the overwhelmingly
        common case."""
        device = device_for_entity(self.hass, entity_id)
        if device is None:
            return None
        network_id = zigbee_network_id(self.hass, device)
        if network_id is None:
            return None
        return f"{network_id}|{device.manufacturer}|{device.model}|{to_version}"

    async def async_request_install(
        self,
        entity_id: str,
        to_version: str,
        service_data: dict[str, Any],
        *,
        is_auto: bool,
        context: AutoInstallContext | None = None,
    ) -> RequestResult:
        """The one shared gate every dispatch path (install_manager.py's own
        auto-install, websocket_api.py's single-entity Install, and the
        panel's Update All, looped per entity) calls before actually
        touching `update.install` itself. Returns "dispatch" (caller
        proceeds exactly as it already does today) for anything that isn't
        part of an active multi-device Zigbee rollout, which is the
        overwhelming majority case, this module stays fully invisible
        until there's actually more than one device to pace against.
        `context` only ever comes from install_manager.py's own auto-install
        path (is_auto=True); a manual dispatch has no reason/timing to
        attribute at all."""
        group_key = self._group_key_for(entity_id, to_version)
        if group_key is None:
            return "dispatch"

        existing = self._queues.get(group_key)
        if existing:
            for entry in existing:
                if entry.entity_id == entity_id:
                    # Already recorded (e.g. a duplicate request for the
                    # same entity/version), whatever its current position
                    # already decided stands, don't add a second entry.
                    return "dispatch" if existing[0] is entry else "queued"
            existing.append(_QueuedEntry(entity_id, to_version, service_data, is_auto, context))
            await self._async_save()
            return "queued"

        # First time this exact group has been asked to install at all:
        # nothing to pace against yet, go immediately. The queue is created
        # now (as a 1-entry list) so a *second*, later request against the
        # same group, while this one is still in flight, has something
        # to wait behind (the branch above). rollout_groups_snapshot/
        # is_queued below both deliberately ignore single-entry queues, so
        # this doesn't show any UI on its own yet.
        self._queues[group_key] = [_QueuedEntry(entity_id, to_version, service_data, is_auto, context)]
        await self._async_save()
        return "dispatch"

    @callback
    def _on_install_completed(self, entity_id: str, old_version: str, new_version: str, new_state: State) -> None:
        for group_key, entries in self._queues.items():
            if entries and entries[0].entity_id == entity_id and entries[0].to_version == new_version:
                self.hass.async_create_task(self._async_advance(group_key))
                return

    async def _async_advance(self, group_key: str) -> None:
        """The front entry of this group just finished, drop it, and if
        anything's still waiting behind it, dispatch that one now."""
        entries = self._queues.get(group_key)
        if not entries:
            return
        entries.pop(0)
        if not entries:
            del self._queues[group_key]
            await self._async_save()
            return
        await self._async_save()
        await self._async_dispatch(entries[0])

    async def _async_dispatch(self, entry: _QueuedEntry) -> None:
        if entry.is_auto and self._mark_recently_executed is not None:
            # entry.context is only ever None for an is_auto=True entry
            # that was queued (and persisted) before this session's
            # trusted-voter feature added the field at all -- found by
            # review: an unconditional `and entry.context is not None` here
            # would silently skip mark_recently_executed for exactly that
            # entry, misattributing a genuinely automatic install as manual
            # once its turn in the queue finally comes after upgrading.
            # Falling back to a plain "rules" context (no trusted-voter
            # detail, since none was ever recorded for it) keeps the
            # is_auto=True marker meaningful either way.
            context = entry.context or AutoInstallContext(
                to_version=entry.to_version, reason="rules", trusted_voter_usernames=[], announced_at=None
            )
            self._mark_recently_executed(entry.entity_id, context)
        try:
            await self.hass.services.async_call("update", "install", entry.service_data, blocking=True)
        except Exception:
            # Found by review: previously unguarded, a real install failure
            # here left the entry stuck at the front of its queue forever
            # (the only thing that ever advances a queue is the install-
            # completion event, which a failed install never fires), with
            # every sibling device queued behind it blocked too and no
            # failure notification anywhere, unlike a plain, non-queued
            # auto-install's own path. Deliberately does NOT auto-advance
            # past the failure: staying stuck (with a clear notification,
            # not silent) is the safer default for a feature whose whole
            # point is mesh stability, rather than guessing it's safe to
            # move on to the next device.
            _LOGGER.exception("Update Manager's queued install failed for %s", entry.entity_id)
            if self._handle_install_failure is not None:
                self._handle_install_failure(entry.entity_id, entry.to_version)

    async def _async_recover_after_restart(self) -> None:
        """Different Zigbee groups (different networks, or different
        device models on the same network) are fully independent of each
        other, so recovered concurrently, not one at a time: a slow
        firmware flash for one group's re-dispatch shouldn't hold up
        checking/recovering every other unrelated group queued behind it."""
        await asyncio.gather(*(self._async_recover_one(group_key) for group_key in list(self._queues)))

    async def _async_recover_one(self, group_key: str) -> None:
        """Neither "the front entry is still genuinely mid-install" nor
        "it already finished" can be assumed after a restart, no task or
        callback survives one, and the install-listener event that would
        normally tell us either already fired while nothing was listening,
        or never got the chance to. Check the entity's real, current state
        against what it was queued for instead of guessing."""
        entries = self._queues.get(group_key)
        if not entries:
            return
        front = entries[0]
        state = self.hass.states.get(front.entity_id)
        installed = state.attributes.get("installed_version") if state else None
        if installed == front.to_version:
            # Actually finished while HA was down (or in the gap between
            # dispatch and this restart), advance now instead of waiting
            # for an event that already happened.
            await self._async_advance(group_key)
        else:
            # The previous restart interrupted the in-flight install
            # itself. Re-dispatch rather than leaving the group stuck
            # waiting forever for a completion that will never come:
            # calling update.install again is expected to be a safe no-op
            # in the (rarer) case it turns out the install did finish
            # right at the restart boundary, same "calling it again is
            # harmless" reasoning staging_skip.py already relies on for
            # update.skip/clear_skipped, though worth a real live check
            # during testing, not just assumed.
            await self._async_dispatch(front)

    def rollout_groups_snapshot(self) -> list[dict[str, Any]]:
        """Read by websocket_api.py's own _handle_updates to show the
        panel's queue card(s). Only ever returns groups with 2+ entries:
        a lone in-flight entry isn't a queue worth showing, see this
        module's own docstring (reactive, not proactive)."""
        groups = []
        for group_key, entries in self._queues.items():
            if len(entries) < 2:
                continue
            # The network kind is whatever prefix zigbee_network_id itself
            # chose (see _group_key_for: group_key's first "|"-separated
            # segment is that same network_id verbatim), read back out here
            # instead of re-hardcoding "z2m:" as a second, independent
            # literal that would silently drift if zigbee.py's own prefix
            # ever changed.
            network_id = group_key.split("|", 1)[0]
            network = network_id.split(":", 1)[0]
            groups.append(
                {
                    "key": group_key,
                    "network": network,
                    "to_version": entries[0].to_version,
                    "entities": [
                        {"entity_id": e.entity_id, "status": "installing" if i == 0 else "queued"}
                        for i, e in enumerate(entries)
                    ],
                }
            )
        return groups

    def is_queued(self, entity_id: str) -> bool:
        """True only for an entity waiting its turn (not the front/in-flight
        entry) in a group that actually has more than one entry, used by
        staging_skip.py, same "don't hide the lone in-flight one" reasoning
        as rollout_groups_snapshot above."""
        for entries in self._queues.values():
            if len(entries) < 2:
                continue
            if any(e.entity_id == entity_id for e in entries[1:]):
                return True
        return False
