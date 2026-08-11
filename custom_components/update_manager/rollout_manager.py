"""Paces firmware installs across Zigbee devices sharing the same network,
one device at a time, not all at once (real radio traffic that can
destabilize the mesh otherwise) -- any two Zigbee devices on that network,
not just identical ones sharing a model, since the radio bandwidth/mesh
load this guards against is a whole-network fact, not something that
differs by device model or by ZHA vs Zigbee2MQTT. Broadened 2026-08-09
after the original narrower "same model" scoping (2026-07-22) left two
genuinely different Zigbee devices (a sensor and a switch, both via
Zigbee2MQTT) installing fully independently of each other -- not the
intended behavior. See zigbee.py for how a device is
recognized as Zigbee at all and which network it belongs to.

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
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant, State, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .announcer import AutoInstallContext
from .const import DOMAIN, localized_strings
from .coordinator import UpdateManagerCoordinator
from .install_tiers import TIER_RANK, tier_for_entity
from .zigbee import device_for_entity, is_zigbee_entity, zigbee_network_id

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_rollout_queues"

RequestResult = Literal["dispatch", "queued"]

_PANEL_UPDATES_URL = "/update-manager/updates"

_STALLED_NOTIFICATION_ID_PREFIX = f"{DOMAIN}_stalled_install_"

# Public (no leading underscore): repairs.py imports this directly instead
# of keeping its own independently-defined copy -- found by code review,
# 2026-08-10, the two used to drift apart on purpose only in comments
# ("see _async_maybe_raise_stuck_issue"), not in code.
STUCK_ISSUE_ID_PREFIX = "install_stuck_"


def stuck_issue_id(entity_id: str) -> str:
    return f"{STUCK_ISSUE_ID_PREFIX}{entity_id}"

# hass.config.language-driven, same convention install_manager.py's own
# _NOTIFICATION_STRINGS/localized_strings already uses (that shared helper
# now lives in const.py, importable by both without a circular import --
# install_manager.py itself imports RolloutManager from this module).
# An install that never finished, silently advanced past to let the rest of
# the queue continue (see _async_advance_past_stalled_front), used to have
# nothing telling the user that happened at all -- found live, testing an
# actual Zigbee2MQTT device that sat at 0% for a couple of minutes before
# giving up. Deliberately a distinct notification from install_manager.py's
# own "Update failed" one
# (_FAILURE_NOTIFICATION_STRINGS): that's for a dispatch call that raised
# outright (a real error), this is for an install that started normally and
# simply never completed -- a different, much more common situation, not
# obviously a fault, especially for a battery-powered Zigbee end device.
_STALLED_NOTIFICATION_STRINGS = {
    "en": {
        "title": "Update didn't finish",
        # No mention of "the rest of the queue" here at all -- found live:
        # every Zigbee dispatch, even a lone one with no siblings, creates a
        # 1-entry bookkeeping "queue" internally (see
        # _async_request_past_tier_gate's own comment), so that framing read
        # as nonsense for the common case of a single device stalling on its
        # own, with nothing ever actually queued behind it. What matters to
        # the user is simply that this one didn't install and what to do
        # about it, not this module's own internal queue bookkeeping.
        "body_zigbee": (
            "**{name}** didn't install successfully. Is this a battery-powered Zigbee device? It may "
            "need to be woken up first (for example by pressing a button on the device) before the "
            "update can actually start. Try that, then install it again from the "
            "[Update Manager page]({url})."
        ),
        "body_neutral": (
            "**{name}** didn't install successfully. Try installing it again from the "
            "[Update Manager page]({url})."
        ),
    },
    "nl": {
        "title": "Update niet gelukt",
        "body_zigbee": (
            "De installatie van **{name}** is niet gelukt. Is dit een batterij-gevoed Zigbee-apparaat? "
            "Dan moet het misschien eerst wakker gemaakt worden (bijvoorbeeld door op een knopje op "
            "het apparaat te drukken) voordat de update daadwerkelijk kan starten. Probeer dat, en "
            "installeer daarna opnieuw via de [Update Manager-pagina]({url})."
        ),
        "body_neutral": (
            "De installatie van **{name}** is niet gelukt. Installeer opnieuw via de "
            "[Update Manager-pagina]({url})."
        ),
    },
}

# An entity that's been unavailable this long no longer counts as "blocking"
# for the tier gate below. Deliberately short and deliberately never
# notified about (contrast with
# _STUCK_THRESHOLD below): genuinely offline is common and usually resolves
# itself (the update simply reappears once the device reconnects), not
# something worth interrupting anyone over.
_UNAVAILABLE_GRACE = timedelta(minutes=2)

# How long an entity can stay genuinely, continuously in_progress (present,
# not unavailable) before this module raises a Repair issue about it --
# only actually used for an entity that reports no update_percentage at all
# (see _STALL_WINDOW below for one that does): with no progress signal at
# all, there's no way to tell "genuinely still working, just slow" apart
# from "stalled", so this stays a flat duration rather than the faster,
# evidence-based check below. Originally 3 hours for every entity regardless
# of whether it reports progress -- lowered to 1 hour for this
# no-progress-signal fallback specifically, once
# _STALL_WINDOW took over the percentage-reporting case (the actual
# motivating scenario, a Zigbee2MQTT sleepy end device, does report
# percentage) with something faster and better-evidenced than a blind
# duration.
_STUCK_THRESHOLD = timedelta(hours=1)

# For an entity that DOES report update_percentage (both ZHA and
# Zigbee2MQTT report this for a real Zigbee OTA): flagged the moment it
# hasn't gone up for this long, regardless of total elapsed time -- a real
# percentage that's stopped climbing is stronger, faster evidence of a
# genuine stall than any fixed duration could be. Compared against when
# percentage was last seen to increase (each entity's own
# progress_last_increase_at in self._in_flight), not install start -- an
# entity whose percentage climbs steadily for hours never trips this at
# all, only one that's gone quiet does.
_STALL_WINDOW = timedelta(minutes=15)

_RECHECK_INTERVAL = timedelta(seconds=30)

# How long a freshly-dispatched queue front gets before _async_recheck_
# queue_fronts is allowed to conclude it's stalled at all -- found live,
# 2026-08-10, after two Zigbee updates ended up installing at the same
# time: calling update.install doesn't mean in_progress is true by the
# time it returns (same "blocking=True doesn't
# guarantee attribute propagation" gap found earlier this session for
# update.clear_skipped) -- a periodic tick landing in that narrow window,
# seconds after dispatch, saw in_progress still false and wrongly concluded
# the front had already stalled and reverted, advancing the queue and
# dispatching the next device while the "stalled" one was genuinely, if
# slowly, still installing in the background. Confirmed live: a real device
# reporting 7%/12%/22% over the next hour got this exact false "didn't
# install successfully" notification 3 seconds after being dispatched.
_FRONT_GRACE = timedelta(seconds=60)

# How long recently_installing_entity_ids (below) keeps reporting an entity
# as installing after the last time in_progress was actually observed true
# on the 30-second periodic tick, even while it currently reads false --
# found live, 2026-08-10: the panel's own "is this entity installing" check
# has no memory of its own that survives a page reload/panel re-entry (a
# fresh browser-side instance starts with nothing), so a render landing
# exactly when a sleepy Zigbee end device's own in_progress happened to be
# false between wake cycles showed no spinner at all -- consistently
# reproducible right after leaving and re-entering the panel, or refreshing
# it, unlike a render from an *already-running* panel instance (which does
# have its own short-term memory of the same thing, added alongside this).
# This module's own tracking doesn't reset just because the browser tab
# did, so it's a source of truth that survives exactly that gap. Longer
# than _FRONT_GRACE above since this is only sampled once every 30 seconds
# (_RECHECK_INTERVAL), not continuously -- needs to comfortably span
# several ticks, not just bridge one continuous check.
_RECENTLY_INSTALLING_GRACE = timedelta(minutes=2)


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


def _serialize_entry(entry: "_QueuedEntry") -> dict[str, Any]:
    return {
        "entity_id": entry.entity_id,
        "to_version": entry.to_version,
        "service_data": entry.service_data,
        "is_auto": entry.is_auto,
        "context": _serialize_context(entry.context),
    }


def _deserialize_entry(data: dict[str, Any]) -> "_QueuedEntry":
    return _QueuedEntry(
        data["entity_id"], data["to_version"], data["service_data"], data["is_auto"], _deserialize_context(data.get("context"))
    )


@dataclass
class _InFlightInstall:
    """Everything this module tracks about one entity's own currently (or
    recently) attempted install, consolidated from 4 previously-independent
    dicts/set (self._front_since/_install_started/_progress_last_increase/
    _force_cleared) that each grew as their own separate patch this session
    -- found by code review, 2026-08-10: every lifecycle end (a genuine
    completion, a queue advance past a stalled/finished front) had to
    remember to pop/discard from all 4 individually by hand, four separate
    chances to forget one.

    front_since: when this entity became a Zigbee queue's own front entry
    (see _FRONT_GRACE's own comment). started_at: when it was first
    observed continuously in_progress (see _STUCK_THRESHOLD's own
    comment) -- distinct from front_since, since in_progress can take a
    moment to actually turn true after dispatch. progress_high_water/
    progress_last_increase_at: the evidence-based stall check (see
    _STALL_WINDOW's own comment), only ever populated for an entity that
    reports update_percentage at all. last_true_at: the last periodic tick
    that actually observed in_progress true, regardless of whether
    started_at itself is currently set (see _RECENTLY_INSTALLING_GRACE's
    own comment and recently_installing_entity_ids below) -- a separate,
    purely additive record, never consulted by the stall-detection logic
    above. force_cleared: the manual "stop waiting" override (Repair issue
    fix-flow, or the panel's own dialog button)."""

    front_since: datetime | None = None
    started_at: datetime | None = None
    progress_high_water: float | None = None
    progress_last_increase_at: datetime | None = None
    last_true_at: datetime | None = None
    force_cleared: bool = False


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
        # entity_id -> the request currently held back purely by the tier
        # gate (see _tier_blocking_entity's own docstring) -- unlike
        # self._queues above, this is never keyed by a shared group_key:
        # the tier gate isn't "wait behind this one specific other request",
        # it's "wait until *whatever* is currently blocking, at this exact
        # moment, stops blocking", re-evaluated live on every retry rather
        # than tied to one specific entry. A tier-blocked request that then
        # also turns out to need Zigbee-network pacing moves into self._queues
        # instead once the tier gate actually clears (see
        # _async_dispatch_past_tier_gate).
        self._tier_blocked: dict[str, _QueuedEntry] = {}
        # entity_id -> _InFlightInstall, this module's own consolidated
        # per-entity bookkeeping for a currently (or recently) attempted
        # install -- see that dataclass's own docstring. Deliberately not
        # persisted (an in-flight attempt, or a manual override, is a
        # fact about the current runtime session, not something worth
        # remembering across a restart): a fresh instance simply
        # rediscovers "genuinely in_progress right now" itself, and an
        # abandoned "stop waiting" override with no persisted record
        # behind it is the same "one-off I've decided" behavior this
        # already had before consolidating.
        self._in_flight: dict[str, _InFlightInstall] = {}
        # Told about by __init__.py so a queue-dispatched auto-install still
        # gets correctly attributed in install_log.py, see
        # set_recently_executed_setter's own docstring.
        self._mark_recently_executed: Callable[[str, AutoInstallContext], None] | None = None
        # Same reasoning/wiring as _mark_recently_executed above, see
        # set_failure_handler's own docstring: a queued entry's install can
        # fail too, once this module is the one dispatching it.
        self._handle_install_failure: Callable[[str, str], None] | None = None
        self._unsub_install_listener: Callable[[], None] | None = None
        self._unsub_periodic_recheck: Callable[[], None] | None = None

    def _in_flight_entry(self, entity_id: str) -> _InFlightInstall:
        entry = self._in_flight.get(entity_id)
        if entry is None:
            entry = _InFlightInstall()
            self._in_flight[entity_id] = entry
        return entry

    def _prune_in_flight_if_empty(self, entity_id: str) -> None:
        if self._in_flight.get(entity_id) == _InFlightInstall():
            del self._in_flight[entity_id]

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
        # "queues"/"tier_blocked" wrapper added alongside the tier gate --
        # a file saved before that existed has the queues dict as the whole
        # top-level payload, no wrapper at all. Read as that older shape
        # whenever neither new key is present, so an in-flight Zigbee queue
        # saved before this project's own update isn't silently dropped.
        if "queues" in data or "tier_blocked" in data:
            queues_data = data.get("queues", {})
            tier_blocked_data = data.get("tier_blocked", {})
        else:
            queues_data = data
            tier_blocked_data = {}
        self._queues = {
            group_key: [_deserialize_entry(e) for e in entries] for group_key, entries in queues_data.items()
        }
        self._tier_blocked = {entity_id: _deserialize_entry(e) for entity_id, e in tier_blocked_data.items()}

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "queues": {
                    group_key: [_serialize_entry(e) for e in entries] for group_key, entries in self._queues.items()
                },
                "tier_blocked": {entity_id: _serialize_entry(e) for entity_id, e in self._tier_blocked.items()},
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
        # Drives everything that depends on wall-clock time passing rather
        # than any single HA event firing -- the unavailable-for-2-minutes
        # grace period and the hours-long stuck-issue threshold, neither of
        # which anything else would otherwise ever re-check on its own. See
        # _async_periodic_recheck's own docstring.
        self._unsub_periodic_recheck = async_track_time_interval(self.hass, self._async_periodic_recheck, _RECHECK_INTERVAL)

    @callback
    def async_stop(self) -> None:
        if self._unsub_install_listener is not None:
            self._unsub_install_listener()
            self._unsub_install_listener = None
        if self._unsub_periodic_recheck is not None:
            self._unsub_periodic_recheck()
            self._unsub_periodic_recheck = None

    def _group_key_for(self, entity_id: str) -> str | None:
        """None if this entity isn't a Zigbee device at all (or its device
        can't be resolved), meaning it's never paced, the overwhelmingly
        common case. The network_id alone, not also manufacturer/model/
        to_version -- any two Zigbee
        devices on the same network should pace against each other, not
        just identical ones (see this module's own docstring for why:
        radio bandwidth/mesh load is a whole-network fact)."""
        device = device_for_entity(self.hass, entity_id)
        if device is None:
            return None
        return zigbee_network_id(self.hass, device)

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
        touching `update.install` itself. Two independent gates, checked in
        order, either one enough to hold a request back -- see
        _tier_blocking_entity's own docstring for why the tier gate goes
        first (coarse/global) and the existing Zigbee-network gate second
        (fine-grained/per-network): a ZHA device's own firmware update entity
        is a real example of something genuinely subject to both at once
        (device_class "firmware" for the tier gate, its own Zigbee network
        for the network gate). Returns "dispatch" (caller proceeds exactly as
        it already does today) for the overwhelming majority of requests,
        which clear both gates immediately -- this module stays fully
        invisible until there's actually something to pace against.
        `context` only ever comes from install_manager.py's own auto-install
        path (is_auto=True); a manual dispatch has no reason/timing to
        attribute at all."""
        entry = _QueuedEntry(entity_id, to_version, service_data, is_auto, context)
        blocking = self._tier_blocking_entity(entity_id)
        if blocking is not None:
            self._tier_blocked[entity_id] = entry
            await self._async_save()
            return "queued"
        return await self._async_request_past_tier_gate(entry)

    async def _async_request_past_tier_gate(self, entry: _QueuedEntry) -> RequestResult:
        """The Zigbee-network gate on its own, unchanged in substance from
        this module's own original, tier-gate-less version -- split out so
        _async_retry_tier_blocked below can re-run exactly this same check
        once the tier gate itself clears for an entry, without duplicating
        it."""
        group_key = self._group_key_for(entry.entity_id)
        if group_key is None:
            return "dispatch"

        existing = self._queues.get(group_key)
        if existing:
            for index, existing_entry in enumerate(existing):
                if existing_entry.entity_id != entry.entity_id:
                    continue
                if index == 0:
                    # Already the front, genuinely in flight -- can't
                    # retarget an install that's already been dispatched,
                    # whatever this new request's own to_version is.
                    return "dispatch" if existing_entry.to_version == entry.to_version else "queued"
                if existing_entry.to_version != entry.to_version:
                    # Found by code review, 2026-08-10: this used to match
                    # by entity_id alone, so a later request for a
                    # genuinely newer version (arriving while still queued
                    # behind someone else) silently kept the stale
                    # to_version already recorded here -- once this
                    # entry's own turn finally came, the OLD version got
                    # installed, not the one actually requested. Replace
                    # it with the fresh request instead of keeping the
                    # stale one.
                    existing[index] = _QueuedEntry(
                        entry.entity_id, entry.to_version, entry.service_data, entry.is_auto, entry.context
                    )
                    await self._async_save()
                # Already recorded for this exact version, whatever its
                # current position already decided stands, don't add a
                # second entry.
                return "queued"
            # Re-validate the front entry before trusting it as genuinely
            # still in flight -- found live, 2026-08-10: a brand new install
            # request for an unrelated (if same-network) device showed
            # "Waiting for X", where X was an update already installed.
            # _async_recover_after_restart is
            # what normally cleans up a front entry that finished while HA
            # was down, but it's fired as its own background task, not
            # awaited before async_start returns -- a request landing in
            # that same narrow startup window can reach here before
            # recovery has gotten to this exact group yet. Only the front
            # can ever be genuinely "in flight" (the rest are still
            # waiting their own actual turn, never dispatched, so they
            # can't have silently completed), so only it needs checking.
            front = existing[0]
            front_state = self.hass.states.get(front.entity_id)
            front_installed = front_state.attributes.get("installed_version") if front_state else None
            if front_installed == front.to_version:
                # _async_advance, not a bare pop -- if anything else was
                # already genuinely queued behind this stale front, it
                # needs to actually be dispatched now, not just silently
                # promoted to "front" with nothing ever having told it to
                # install.
                await self._async_advance(group_key)
                existing = self._queues.get(group_key)
            if existing:
                existing.append(entry)
                await self._async_save()
                return "queued"

        # First time this exact group has been asked to install at all:
        # nothing to pace against yet, go immediately. The queue is created
        # now (as a 1-entry list) so a *second*, later request against the
        # same group, while this one is still in flight, has something
        # to wait behind (the branch above). rollout_groups_snapshot/
        # is_queued below both deliberately ignore single-entry queues, so
        # this doesn't show any UI on its own yet.
        self._queues[group_key] = [entry]
        self._in_flight_entry(entry.entity_id).front_since = dt_util.utcnow()
        await self._async_save()
        return "dispatch"

    def _counts_as_blocking(self, entity_id: str, state: State) -> bool:
        """Whether entity_id's own current state should count as "actively
        installing" for the tier gate -- almost always just its own
        in_progress attribute, except while genuinely unavailable, where
        that attribute may just be stale (or missing outright). See
        _UNAVAILABLE_GRACE's own comment for why a short grace period is
        given before an unavailable entity stops counting, rather than
        either extreme (trusting stale in_progress forever, or discounting
        it the instant it goes unavailable). state.last_changed already
        records the exact instant the main state itself last transitioned
        (unlike in_progress, an attribute, not the main state) -- no need
        for this module to track "since when unavailable" by hand."""
        entry = self._in_flight.get(entity_id)
        if entry is not None and entry.force_cleared:
            return False
        if state.state == "unavailable":
            return dt_util.utcnow() - state.last_changed < _UNAVAILABLE_GRACE
        return bool(state.attributes.get("in_progress"))

    def _tier_blocking_entity(self, entity_id: str) -> str | None:
        """The entity_id of some *other* update entity, currently counting
        as blocking (see _counts_as_blocking), at a strictly lower
        disruption tier than entity_id's own (see install_tiers.py's own
        module docstring for the full tier list and the real, confirmed
        reasoning behind each one) -- None if entity_id is itself "safe"
        (nothing is ever below that, so nothing can ever block it) or if
        nothing currently qualifies. A live check, deliberately never
        cached: re-run on every request and every periodic recheck (see
        _async_periodic_recheck), since "what's installing right now"
        changes continuously and this must always reflect the current
        instant, not a stale snapshot."""
        my_rank = TIER_RANK[tier_for_entity(self.hass, entity_id)]
        if my_rank == 0:
            return None
        for other_id in self.hass.states.async_entity_ids("update"):
            if other_id == entity_id:
                continue
            state = self.hass.states.get(other_id)
            if state is None or not self._counts_as_blocking(other_id, state):
                continue
            if TIER_RANK[tier_for_entity(self.hass, other_id)] < my_rank:
                return other_id
        return None

    async def _async_retry_tier_blocked(self) -> None:
        """Re-attempts every still-pending tier-blocked request -- called
        after anything that could plausibly have changed the picture: a
        real install completion, an unavailable entity crossing
        _UNAVAILABLE_GRACE, or a manual "stop waiting" override. Whatever
        clears the tier gate goes through the exact same Zigbee-network check
        every other request does (_async_request_past_tier_gate), and gets
        actually dispatched here if that also says go -- there's no
        external caller left to do that part for a request that's already
        been sitting queued, unlike the normal synchronous
        async_request_install flow.

        "What's currently blocking" is computed once for the whole batch
        (_min_blocking_tier_rank), not once per still-blocked entry the way
        a fresh async_request_install call does via _tier_blocking_entity --
        every entry re-checked here in the same pass is asking the exact
        same question, previously a full, separate entity-registry scan
        each time (found by review: O(blocked x update entities) on every
        30-second recheck)."""
        if not self._tier_blocked:
            return
        min_blocking_rank = self._min_blocking_tier_rank()
        # Saved once for the whole batch below, not once per cleared entry
        # -- found by code review, 2026-08-10: several requests clearing in
        # the same tick (e.g. right after a blocking Core install finishes)
        # used to each trigger their own full Store write.
        cleared_any = False
        for entity_id in list(self._tier_blocked):
            entry = self._tier_blocked.get(entity_id)
            if entry is None:
                continue
            my_rank = TIER_RANK[tier_for_entity(self.hass, entity_id)]
            if min_blocking_rank is not None and min_blocking_rank < my_rank:
                continue
            del self._tier_blocked[entity_id]
            cleared_any = True
            if await self._async_request_past_tier_gate(entry) == "dispatch":
                await self._async_dispatch(entry)
        if cleared_any:
            await self._async_save()

    def _min_blocking_tier_rank(self) -> int | None:
        """The lowest tier rank among every update entity currently
        counting as blocking (see _counts_as_blocking) anywhere on the
        instance, or None if nothing is. Tier-blocked entries are
        themselves never in_progress (they haven't been dispatched yet, by
        definition of being in self._tier_blocked at all), so unlike
        _tier_blocking_entity's own single, ad hoc check (used only by
        async_request_install for a brand new request, never in a batch),
        this never needs to exclude any one specific entity_id from the
        scan."""
        best: int | None = None
        for other_id in self.hass.states.async_entity_ids("update"):
            state = self.hass.states.get(other_id)
            if state is None or not self._counts_as_blocking(other_id, state):
                continue
            rank = TIER_RANK[tier_for_entity(self.hass, other_id)]
            if best is None or rank < best:
                best = rank
        return best

    async def async_stop_waiting_for(self, entity_id: str) -> None:
        """Manual override -- the Repair issue's own fix-flow, or the
        panel's own dialog button, both call this. Stops treating entity_id
        as blocking anything else, regardless of its own real state; does
        *not* touch the install itself, which may well still genuinely be
        running -- if it later actually completes, _on_install_completed's
        own cleanup removes the override the same way it cleans up
        everything else, so this never permanently mismarks an entity."""
        self._in_flight_entry(entity_id).force_cleared = True
        self._async_clear_stuck_issue(entity_id)
        await self._async_retry_tier_blocked()

    async def async_cancel_queued(self, entity_id: str) -> bool:
        """The panel's own Cancel button for a request that's genuinely
        waiting its turn, not yet dispatched -- whichever of the two ways
        that can currently happen: a Zigbee rollout queue entry, or a
        tier-blocked one (held back purely by the disruption-order gate,
        e.g. firmware waiting for an active Core install to finish).
        Lets someone leave that wait and go back to a normal, standalone
        ready update instead of waiting their turn out. Checks
        self._tier_blocked first (a plain removal, no other bookkeeping --
        nothing else needs to change for it to become a normal ready
        update again, exactly like _async_retry_tier_blocked's own removal
        when the block clears on its own), then falls through to the
        Zigbee queues. Within a Zigbee queue, only ever removes entityId
        from wherever it sits behind the front of its own group -- the
        front itself is already actively installing, a different
        operation entirely (not exposed here, see async_stop_waiting_for
        for that one). Either way, the entity's own staging status was
        already "ready" the whole time it sat waiting (see coordinator.py's
        own status computation, entirely independent of this module), so
        nothing else needs to change here for it to show as a normal,
        standalone ready update again -- rollout_groups_snapshot/is_queued
        both already stop counting a group with fewer than 2 entries as an
        active queue at all. Returns whether anything was actually found
        and removed, so a caller can tell a genuine cancel apart from a
        no-op (e.g. this entity's own turn, or its own tier block, had
        already cleared by the time the click landed)."""
        if entity_id in self._tier_blocked:
            del self._tier_blocked[entity_id]
            await self._async_save()
            return True
        for entries in self._queues.values():
            for index, entry in enumerate(entries):
                if index == 0:
                    continue
                if entry.entity_id == entity_id:
                    del entries[index]
                    await self._async_save()
                    return True
        return False

    @callback
    def _on_install_completed(self, entity_id: str, old_version: str, new_version: str, new_state: State) -> None:
        self._in_flight.pop(entity_id, None)
        self._async_clear_stuck_issue(entity_id)
        # A later retry (a manual click, or another auto-install cycle
        # picking the now-standalone entity back up) just genuinely
        # succeeded -- clears any "didn't finish" notification
        # _async_notify_stalled raised for an earlier attempt, same
        # "harmless no-op if nothing's raised" reasoning as the Repair
        # issue's own clear above.
        persistent_notification.async_dismiss(self.hass, f"{_STALLED_NOTIFICATION_ID_PREFIX}{entity_id}")
        self.hass.async_create_task(self._async_retry_tier_blocked())
        group_key = self._group_key_with_front(entity_id)
        if group_key is not None:
            entries = self._queues.get(group_key)
            if entries and entries[0].to_version == new_version:
                self.hass.async_create_task(self._async_advance(group_key))

    async def _async_advance(self, group_key: str) -> None:
        """The front entry of this group just finished (or, per
        _async_advance_past_stalled_front below, gave up on its own without
        ever actually finishing), drop it, and if anything's still waiting
        behind it, dispatch that one now."""
        entries = self._queues.get(group_key)
        if not entries:
            return
        finished = entries.pop(0)
        self._in_flight.pop(finished.entity_id, None)
        if not entries:
            del self._queues[group_key]
            await self._async_save()
            return
        _LOGGER.warning(
            "Update Manager: [rollout] %s advanced, dispatching next in %s: %s",
            finished.entity_id,
            group_key,
            entries[0].entity_id,
        )
        await self._async_save()
        await self._async_dispatch(entries[0])

    def _group_key_with_front(self, entity_id: str) -> str | None:
        for group_key, entries in self._queues.items():
            if entries and entries[0].entity_id == entity_id:
                return group_key
        return None

    async def _async_advance_past_stalled_front(self, entity_id: str, *, notify: bool = True) -> None:
        """entity_id was the front of a Zigbee rollout queue and just
        stopped counting as actively installing, without this module ever
        seeing a real completion for it (see _on_install_completed's own
        version-change requirement) -- called both right after a dispatch
        call itself failed outright (_async_dispatch's own except-branch)
        and once a periodic recheck notices in_progress went back to false
        on its own (_async_recheck_stuck_installs). Without this, the
        group's queue waits forever: the only other thing that ever
        advances it is a genuine completion, which neither a failed
        dispatch nor a stalled install ever produces.

        Real-world case: a Zigbee2MQTT sleepy end device's own in_progress
        toggles false between wake cycles just as readily as a genuine
        failure would, and there's no way to tell the two apart from here.
        Explicit, informed tradeoff: advance immediately either way, rather
        than waiting for a long grace period
        or a genuine completion -- the alternative left every other device
        in the same group waiting behind an indefinitely stalled front with
        nothing to show for it. A stalled front entity itself is simply
        dropped from the queue here, not retried automatically: it reverts
        to a normal, standalone pending update (still genuinely available,
        HA's own installed_version never changed), the same as if it had
        never been queued at all -- a later Update All click or auto-install
        cycle can pick it up again like any other pending update.

        Re-checks installed_version against the front entry's own to_version
        first, same defensive check _async_recover_one already uses for the
        analogous restart-recovery case: this method's own three callers
        (_async_dispatch's except-branch, _async_recheck_stuck_installs,
        _async_recheck_queue_fronts) all run on entirely separate scheduling
        from _on_install_completed
        (the real, coordinator-driven completion path), so a genuine
        completion landing at almost the same moment this fires must not
        be double-handled as a stall instead.

        `notify` is False only for _async_dispatch's own except-branch
        caller, which already raises its own, differently-worded
        persistent_notification for that specific case (install_manager.py's
        own handle_install_failure, shared via set_failure_handler) -- a
        dispatch call raising outright is a genuine error, not the same
        situation as an install that started normally and simply never
        finished, which is what _async_notify_stalled below is actually
        about (and where a real Zigbee end-device's own wake-up tip
        belongs)."""
        group_key = self._group_key_with_front(entity_id)
        if group_key is None:
            return
        entries = self._queues.get(group_key)
        front = entries[0] if entries else None
        if front is None:
            return
        # See _FRONT_GRACE's own comment: calling update.install doesn't
        # mean in_progress is true by the time it returns, so a fresh
        # dispatch needs a moment before "not in_progress right now" can be
        # trusted as evidence of a stall rather than just "hasn't started
        # reporting yet". Confirmed live: without this, a real device still
        # genuinely installing (just slowly) got advanced past within
        # seconds of being dispatched, leaving it running in the background
        # at the same time as the next device in the queue.
        in_flight = self._in_flight.get(entity_id)
        front_since = in_flight.front_since if in_flight else None
        if front_since is not None and dt_util.utcnow() - front_since < _FRONT_GRACE:
            return
        state = self.hass.states.get(entity_id)
        installed = state.attributes.get("installed_version") if state else None
        if installed == front.to_version:
            return
        if notify:
            self._async_notify_stalled(entity_id)
        await self._async_advance(group_key)

    def _async_notify_stalled(self, entity_id: str) -> None:
        """Nudges someone to wake a battery-powered Zigbee device so its
        stalled install can actually proceed. Every entity that ever
        reaches here is a genuine Zigbee device by construction
        (_group_key_with_front only ever matches something that entered
        self._queues in the first place, which only happens for a real
        Zigbee network_id, see _group_key_for), so is_zigbee_entity below
        is a defensive check, not expected to ever actually be False --
        same "check it anyway" precedent _async_maybe_raise_stuck_issue
        already sets for its own, near-identical choice of wording."""
        state = self.hass.states.get(entity_id)
        name = state.name if state else entity_id
        strings = localized_strings(self.hass, _STALLED_NOTIFICATION_STRINGS)
        body_key = "body_zigbee" if is_zigbee_entity(self.hass, entity_id) else "body_neutral"
        persistent_notification.async_create(
            self.hass,
            strings[body_key].format(name=name, url=_PANEL_UPDATES_URL),
            title=strings["title"],
            notification_id=f"{_STALLED_NOTIFICATION_ID_PREFIX}{entity_id}",
        )

    async def _async_dispatch(self, entry: _QueuedEntry) -> None:
        self._in_flight_entry(entry.entity_id).front_since = dt_util.utcnow()
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
            # auto-install's own path.
            _LOGGER.exception("Update Manager's queued install failed for %s", entry.entity_id)
            if self._handle_install_failure is not None:
                self._handle_install_failure(entry.entity_id, entry.to_version)
            # Advances past it immediately if it was a Zigbee queue's own
            # front entry -- a no-op for anything else (never entered
            # self._queues at all). notify=False: _handle_install_failure
            # just above already raised its own notification for this
            # exact case. See _async_advance_past_stalled_front's own
            # docstring for the reasoning behind this.
            await self._async_advance_past_stalled_front(entry.entity_id, notify=False)

    @callback
    def _async_periodic_recheck(self, now: datetime) -> None:
        """Drives everything that needs wall-clock time to pass rather than
        any single HA event to react to -- nothing else would otherwise
        ever notice an in-progress entity quietly crossing
        _STUCK_THRESHOLD, since that's not a state *change* on its own.
        (The unavailable-for-_UNAVAILABLE_GRACE side of the tier gate needs
        no timer of its own: _counts_as_blocking reads state.last_changed
        directly, live, whenever it's asked.) The stuck-install watchdog
        below and the tier gate's own retry are two independent concerns
        that both happen to need a wall-clock tick, not one intertwined
        mechanism -- kept as two named steps sharing this one timer."""
        self._async_recheck_stuck_installs(now)
        self.hass.async_create_task(self._async_retry_tier_blocked())
        self.hass.async_create_task(self._async_recheck_queue_fronts())

    async def _async_recheck_queue_fronts(self) -> None:
        """Validates every Zigbee queue's own front entry against real HA
        state on every tick, not just reactively when a fresh install
        request happens to land against that exact group (see
        _async_request_past_tier_gate's own defensive check, and
        _async_advance_past_stalled_front, both narrower: only triggered
        by *something happening* against that specific group). Found
        live, 2026-08-10: a queue's front entity
        that quietly finished (or even stopped having a pending update at
        all) with nothing ever asking to install that same network again
        just sat there forever -- still shown as "installing", with
        whatever was queued behind it stuck showing "Waiting for X to
        finish" for an X that wasn't doing anything, wasn't even pending
        anymore. Skips anything currently genuinely in_progress -- this
        must never interrupt (or repeatedly re-dispatch) a real, ongoing
        install, only clean up one that's already, genuinely done or
        gone."""
        for group_key in list(self._queues):
            entries = self._queues.get(group_key)
            if not entries:
                continue
            front = entries[0]
            state = self.hass.states.get(front.entity_id)
            if state is not None and state.attributes.get("in_progress"):
                continue
            installed = state.attributes.get("installed_version") if state else None
            if installed == front.to_version:
                # Genuinely completed -- a confirmed fact, always safe to
                # advance immediately regardless of _FRONT_GRACE. Handled
                # explicitly here (not through _on_install_completed's own
                # listener) specifically for the case this function's own
                # docstring describes: nothing else ever asked to install
                # this network again, so nothing else was listening either.
                await self._async_advance(group_key)
                continue
            # Not confirmed complete -- unavailable, no longer pending, or
            # genuinely stalled while still pending are all handled the
            # same way from here, via the same grace-respecting,
            # notifying path _async_recheck_stuck_installs already uses.
            # Found by code review, 2026-08-10: this used to advance
            # immediately whenever the entity was merely unavailable or
            # briefly not reporting "on" (`not still_pending`), bypassing
            # _FRONT_GRACE entirely -- a Zigbee device going briefly
            # unavailable seconds after dispatch (a real, common MQTT
            # reconnect blip) hit that branch directly and got advanced
            # past immediately, reopening the exact double-dispatch race
            # _FRONT_GRACE exists to close.
            await self._async_advance_past_stalled_front(front.entity_id)

    def _async_recheck_stuck_installs(self, now: datetime) -> None:
        """Maintains each in-flight entity's started_at (when it was first
        observed continuously in_progress) and progress_high_water/
        progress_last_increase_at (highest update_percentage seen and when
        it last went up, only for an entity that reports one at all), and
        raises/clears this entity's Repair issue once _stuck_since_for
        crosses whichever of _STALL_WINDOW/_STUCK_THRESHOLD applies -- the
        watchdog side of this module, unrelated to which tier is currently
        blocking what (see _async_periodic_recheck's own docstring)."""
        for entity_id, entry in list(self._in_flight.items()):
            if entry.started_at is None:
                continue
            state = self.hass.states.get(entity_id)
            if state is None or not state.attributes.get("in_progress"):
                entry.started_at = None
                entry.progress_high_water = None
                entry.progress_last_increase_at = None
                self._prune_in_flight_if_empty(entity_id)
                self._async_clear_stuck_issue(entity_id)
                # Found live, 2026-08-09, watching a real device sit at 0%
                # for about two minutes then stop, with the sibling queued
                # behind it never advancing either: this call was
                # missing entirely -- _async_advance_past_stalled_front's
                # own docstring already claimed this was one of its two
                # callers, but only _async_dispatch's except-branch (a
                # dispatch call itself raising synchronously) was actually
                # wired up. This, the far more common case -- in_progress
                # genuinely going back to false some time later, exactly
                # what just happened -- never advanced the queue at all.
                self.hass.async_create_task(self._async_advance_past_stalled_front(entity_id))
        for entity_id in self.hass.states.async_entity_ids("update"):
            state = self.hass.states.get(entity_id)
            if state is not None and state.attributes.get("in_progress"):
                entry = self._in_flight_entry(entity_id)
                # Refreshed unconditionally, unlike started_at right below --
                # see _RECENTLY_INSTALLING_GRACE's own comment, this is a
                # separate, purely additive record of "still counts as
                # installing for display purposes", not part of the stall-
                # detection decision the rest of this method makes.
                entry.last_true_at = now
                if entry.started_at is None:
                    entry.started_at = now
        for entity_id, entry in list(self._in_flight.items()):
            if entry.last_true_at is not None and now - entry.last_true_at >= _RECENTLY_INSTALLING_GRACE:
                entry.last_true_at = None
                self._prune_in_flight_if_empty(entity_id)
            if entry.started_at is None:
                continue
            state = self.hass.states.get(entity_id)
            percentage = state.attributes.get("update_percentage") if state else None
            if percentage is not None:
                if entry.progress_high_water is None or percentage > entry.progress_high_water:
                    entry.progress_high_water = percentage
                    entry.progress_last_increase_at = now
                    # A real increase is direct evidence this wasn't (or is
                    # no longer) actually stalled -- self-heals any Repair
                    # issue already raised while in_progress itself never
                    # went false (the only other place that clears one).
                    # Harmless no-op if nothing's currently raised.
                    self._async_clear_stuck_issue(entity_id)
            since = self._stuck_since_for(entity_id)
            threshold = _STALL_WINDOW if entry.progress_last_increase_at is not None else _STUCK_THRESHOLD
            if since is not None and now - since >= threshold:
                self._async_maybe_raise_stuck_issue(entity_id, since)

    def recently_installing_entity_ids(self, now: datetime) -> list[str]:
        """Read by websocket_api.py so the panel's own "is this entity
        still installing" decision has a source of truth that survives a
        page reload/panel re-entry -- see _RECENTLY_INSTALLING_GRACE's own
        comment for why the panel's own, necessarily-empty-on-a-fresh-load
        client-side memory isn't enough on its own."""
        return [
            entity_id
            for entity_id, entry in self._in_flight.items()
            if entry.last_true_at is not None and now - entry.last_true_at < _RECENTLY_INSTALLING_GRACE
        ]

    def _stuck_since_for(self, entity_id: str) -> datetime | None:
        """The "since when has this looked stuck" reference both
        _async_recheck_stuck_installs and stuck_since_snapshot need: the
        last time update_percentage was seen to increase, for an entity
        that reports one at all (see _STALL_WINDOW's own comment -- a real
        stall is evidenced directly, not inferred from a blind duration),
        else when it was first observed continuously in_progress (see
        _STUCK_THRESHOLD's own comment, the no-progress-signal fallback)."""
        entry = self._in_flight.get(entity_id)
        if entry is None:
            return None
        if entry.progress_last_increase_at is not None:
            return entry.progress_last_increase_at
        return entry.started_at

    def _async_maybe_raise_stuck_issue(self, entity_id: str, since: datetime) -> None:
        """Raises a fixable Repair issue the first time entity_id crosses
        whichever threshold applies to it (a no-op on every later recheck
        while it's still raised -- checked directly against the issue
        registry itself rather than a second, hand-kept "did I already
        raise this" set that could drift from what's actually registered)
        -- proactively surfacing a stuck install is the whole point of an
        integration whose job is helping with updates in the first place.
        Text differs for a genuine
        Zigbee end-device (the battery-powered-devices-often-need-waking-up
        tip actually applies there) versus everything else (host firmware,
        Supervisor, an ordinary WiFi device...), where that same tip would
        just be a wrong guess -- see repairs.py's own ConfirmRepairFlow for
        what "Fix" actually does (async_stop_waiting_for, never touches the
        install itself). `since` may now be well under an hour (a real
        percentage stall, see _STALL_WINDOW), so the shown duration is
        always in minutes, not the old, coarser "hours" -- direct user
        feedback, 2026-08-09: keep the notification copy honest for both
        the fast, evidence-based path and the slow, duration-only one."""
        if ir.async_get(self.hass).async_get_issue(DOMAIN, stuck_issue_id(entity_id)) is not None:
            return
        minutes = max(1, int((dt_util.utcnow() - since).total_seconds() // 60))
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            stuck_issue_id(entity_id),
            is_fixable=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key="install_stuck_zigbee" if is_zigbee_entity(self.hass, entity_id) else "install_stuck",
            translation_placeholders={"entity_id": entity_id, "minutes": str(minutes)},
            data={"entity_id": entity_id},
        )

    def _async_clear_stuck_issue(self, entity_id: str) -> None:
        ir.async_delete_issue(self.hass, DOMAIN, stuck_issue_id(entity_id))

    async def _async_recover_after_restart(self) -> None:
        """Different Zigbee groups (different networks, or different
        device models on the same network) are fully independent of each
        other, so recovered concurrently, not one at a time: a slow
        firmware flash for one group's re-dispatch shouldn't hold up
        checking/recovering every other unrelated group queued behind it.
        Tier-blocked entries (see _tier_blocked) were never actually
        dispatched at all, unlike the Zigbee groups above, so there's no
        "did it finish or get interrupted" question to answer for them --
        just re-check whether each is still genuinely blocked given the
        instance's real, current state, exactly like any other retry. Most
        of the time this is precisely a Core/OS-triggered restart that just
        cleared the very thing that was blocking them."""
        await asyncio.gather(*(self._async_recover_one(group_key) for group_key in list(self._queues)))
        await self._async_retry_tier_blocked()

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
            # group_key is now the network_id verbatim (see _group_key_for),
            # not a composite with manufacturer/model/to_version appended --
            # the network kind is still whatever prefix zigbee_network_id
            # itself chose, read back out here instead of re-hardcoding
            # "z2m:" as a second, independent literal that would silently
            # drift if zigbee.py's own prefix ever changed.
            network = group_key.split(":", 1)[0]
            groups.append(
                {
                    "key": group_key,
                    "network": network,
                    # The front entry's own target version -- entries no
                    # longer share one (see _group_key_for's own comment,
                    # 2026-08-09: paced by network alone now, not also by
                    # model/version), so this is informational about
                    # what's currently installing, not the whole group's.
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

    def tier_blocked_entity_ids(self) -> list[str]:
        """Read by websocket_api.py's own _handle_updates, alongside
        rollout_groups_snapshot above -- the panel's own "Installing"
        section shows these with the generic "Waiting for other updates to
        finish first" badge (never naming a specific entity the way the
        Zigbee rollout queue's own badge does: the tier ahead can be
        several entities at once, e.g. every "safe" update in the same
        batch, so there's no one name to point at)."""
        return list(self._tier_blocked)

    def stuck_since_snapshot(self) -> dict[str, dict[str, Any]]:
        """Read by websocket_api.py's own _handle_updates -- entity_id ->
        {"since": ISO 8601, "is_zigbee": bool}, for every entity with an
        active Repair issue right now (see _async_maybe_raise_stuck_issue).
        "since" is the exact same _stuck_since_for reference the Repair
        issue's own duration was computed from (a real, live-updating
        duration instead of a vague "a while") -- for an entity whose
        percentage is genuinely still climbing after the issue was raised
        on an earlier stall, this naturally keeps moving forward with each
        new increase, same live picture the Repair issue's own re-check
        (_async_clear_stuck_issue, via the in_progress-false branch above)
        would eventually reflect too. The panel's own dialog needs
        "is_zigbee" itself to choose between the battery-wake-up tip and
        the neutral "kan nog gewoon goedkomen" text (see
        _async_maybe_raise_stuck_issue's own translation_key choice) --
        deliberately resolved here, not duplicated as a second, independent
        Zigbee-detection implementation in JS, which could silently drift
        from zigbee.py's own real rules over time. "Active Repair issue" is
        read straight from the issue registry itself (same source
        _async_maybe_raise_stuck_issue/_async_clear_stuck_issue write to),
        not a second, hand-kept set that could drift from it."""
        registry = ir.async_get(self.hass)
        result: dict[str, dict[str, Any]] = {}
        for entity_id, entry in self._in_flight.items():
            if entry.started_at is None:
                continue
            if registry.async_get_issue(DOMAIN, stuck_issue_id(entity_id)) is None:
                continue
            since = self._stuck_since_for(entity_id)
            if since is None:
                continue
            result[entity_id] = {"since": since.isoformat(), "is_zigbee": is_zigbee_entity(self.hass, entity_id)}
        return result
