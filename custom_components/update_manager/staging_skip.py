"""Opt-in: while an update is still "waiting" (Fase 0's staging, not yet
"ready"), mark it skipped via HA's own real `update.skip` service -- an
update entity with skipped_version == latest_version reports state "off"
(homeassistant/components/update/__init__.py's own state_attributes/state
logic, confirmed against source, not guessed), the same as "up to date",
so it disappears from HA's own sidebar update count and any other native
"updates available" surface, not just from Update Manager's own panel.
Automatically un-skipped (`update.clear_skipped`) once the entity actually
reaches "ready".

The one real risk this whole module exists to avoid: HA's `skipped_version`
is a single flag with no memory of *why* it was set. If Update Manager
skipped something and later blindly un-skips everything it sees skipped,
it would just as happily clear a skip the user set themselves for their
own unrelated reason. So every skip/unskip this module performs is
recorded in its own persisted store first, and it only ever acts on -- or
even touches -- an entity_id/version pair it recorded there itself. Direct
user feedback (2026-07-17): confirmed worth building, with this exact
distinction as the condition for doing it at all.
"""
from __future__ import annotations

import asyncio
import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .coordinator import UpdateManagerCoordinator
from .rollout_manager import RolloutManager

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_staging_skip"


class StagingSkipManager:
    def __init__(self, hass: HomeAssistant, coordinator: UpdateManagerCoordinator, rollout_manager: RolloutManager) -> None:
        self.hass = hass
        self._coordinator = coordinator
        # A device waiting its turn in a Zigbee rollout queue (see
        # rollout_manager.py) is the same kind of "not actually actionable
        # right now" state this whole module already hides for a plain
        # "waiting" update, see _async_evaluate_one's own use of this.
        self._rollout_manager = rollout_manager
        self._store: Store[dict[str, str]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        # entity_id -> the to_version *we* skipped it for -- never anyone
        # else's skip, see this module's own docstring.
        self._skipped: dict[str, str] = {}
        self._enabled = False
        self._unsub_listener = None
        # Serializes every pass that reads/writes self._skipped against
        # every other one. Found live (2026-07-17, after a restart left
        # almost everything "Skipped" instead of "Postponed"): _on_recompute
        # schedules a brand-new _async_evaluate_all() task on *every*
        # coordinator recompute, with no guard against one already being
        # in flight. When several entities get auto-skipped around the same
        # time (typical right after a restart), each one's own resulting
        # state_changed event -- fired the moment its own update.skip
        # service call resolves -- triggers another recompute, and so
        # another _async_evaluate_all(), before the *first* pass's own
        # asyncio.gather over several concurrent _async_skip calls had
        # necessarily finished waiting on every one of them. That second,
        # overlapping pass then saw self._skipped already holding the first
        # pass's optimistic record for an entity whose service call was
        # still in flight -- skipped_version not yet set in real HA state --
        # which is indistinguishable, from inside _async_evaluate_one, from
        # "the user cleared this skip themselves". It deleted the record
        # the first pass's own in-flight call was about to make true. Once
        # that call actually completed moments later, is_own_skip had
        # nothing left to match: a plain auto-skip permanently
        # misclassified as a genuine user skip, and persisted that way, so
        # it survived even a restart. This lock makes every pass fully see
        # the previous one's finished result instead of a half-applied one.
        self._lock = asyncio.Lock()

    async def async_load(self) -> None:
        self._skipped = await self._store.async_load() or {}

    @property
    def _active(self) -> bool:
        # self._enabled (this module's own hide_postponed setting) and the
        # master pause switch (self._coordinator.master_enabled, const.py's
        # CONF_ENABLED -- read off the coordinator, not a private copy of
        # its own, see coordinator.py's own set_master_enabled) both have to
        # be true for this module to actually skip/unskip anything.
        return self._enabled and self._coordinator.master_enabled

    def async_start(self, enabled: bool) -> None:
        self._enabled = enabled
        self._unsub_listener = self._coordinator.async_add_listener(self._on_recompute)
        # coordinator.py's own initial bulk scan (async_start) doesn't fire
        # listeners itself (see sensor.py's own __init__, which works
        # around the same gap by refreshing once by hand) -- without this,
        # anything already "waiting" at startup wouldn't get evaluated
        # until the next real state_changed or the 15-minute periodic
        # recheck happens to fire.
        self.hass.async_create_task(self._async_evaluate_all())

    @callback
    def async_stop(self) -> None:
        if self._unsub_listener is not None:
            self._unsub_listener()
            self._unsub_listener = None

    def is_own_skip(self, entity_id: str, version: str) -> bool:
        """Read by coordinator.py (see its own set_own_skip_checker,
        wired up by __init__.py) to tell "we skipped this ourselves,
        purely to hide a still-postponed update from HA's own update
        count" apart from a genuine user-initiated skip -- direct user
        feedback: our own skip should read exactly like "postponed" in
        the panel, not as its own distinct "skipped" fact the user never
        actually chose."""
        return self._skipped.get(entity_id) == version

    async def async_forget(self, entity_id: str) -> None:
        """Relinquishes any record this module holds for entity_id --
        called by websocket_api.py's own skip handler (the panel's Skip
        button) before it calls the real update.skip service itself.

        Found live: without this, a user explicitly clicking Skip on an
        entity this module had already auto-skipped for hide_postponed
        was a silent no-op -- skipped_version already equalled
        latest_version in real HA state (so the service call changed
        nothing and fired no state_changed event), and is_own_skip kept
        claiming the entity as "ours", so it stayed classified as
        "waiting"/postponed instead of becoming a real, visible "Skipped"
        the user could actually see reflected."""
        if self._skipped.pop(entity_id, None) is not None:
            await self._store.async_save(self._skipped)

    async def async_update_enabled(self, enabled: bool) -> None:
        """Applies a newly-saved setting in place, no reload needed -- same
        reasoning as install_manager.py's own update_rules. Turning it off
        un-skips everything this module itself skipped, immediately, rather
        than leaving them hidden from HA's own update count until each one
        happens to reach "ready" on its own. Turning it on likewise
        evaluates immediately instead of waiting for the next unrelated
        recompute (a state_changed event or the 15-minute periodic
        recheck) -- found live: saving the setting with it newly turned on
        visibly did nothing until one of those happened to fire on its own,
        which could be minutes away or longer.

        Awaited by the caller (websocket_api.py's save_settings handler),
        not fired as a background task -- found live: the panel's own save
        button reloads Updates/History right after this call resolves, and
        saw stale data (postponed updates that should have just been
        hidden, weren't yet) because the actual skip calls were still
        in-flight in the background at that point."""
        was_active = self._active
        self._enabled = enabled
        await self._async_apply_active_transition(was_active)

    async def async_set_master_enabled(self, enabled: bool) -> None:
        """The global Update Manager pause switch (const.py's CONF_ENABLED)
        -- distinct from this module's own hide_postponed setting
        (self._enabled), applied the same way async_update_enabled applies
        that one: immediately, un-skipping everything this module itself
        skipped the moment the switch turns off (rather than leaving them
        hidden until each one happens to reach "ready" on its own).

        Stores the flag on the coordinator (self._coordinator.master_enabled),
        not a private copy of its own -- see coordinator.py's own
        set_master_enabled for why."""
        was_active = self._active
        self._coordinator.set_master_enabled(enabled)
        await self._async_apply_active_transition(was_active)

    async def _async_apply_active_transition(self, was_active: bool) -> None:
        is_active = self._active
        if was_active and not is_active:
            await self._async_clear_all()
        elif is_active and not was_active:
            await self._async_evaluate_all()

    @callback
    def _on_recompute(self) -> None:
        # Fired synchronously by the coordinator after every recompute (a
        # state_changed, the periodic recheck, or a settings save) --
        # schedule the actual (async, calls real services) evaluation
        # rather than doing it inline here.
        self.hass.async_create_task(self._async_evaluate_all())

    async def _async_clear_all(self) -> None:
        # Serialized against every other pass (see self._lock's own
        # comment) -- concurrent *within* this one call, not one entity at
        # a time (found live: sequential blocking=True service calls made
        # turning this off visibly take a long time on an instance with
        # more than a few skipped entities).
        async with self._lock:
            items = list(self._skipped.items())
            results = await asyncio.gather(
                *(self._async_unskip(entity_id, to_version) for entity_id, to_version in items)
            )
            # Only drop records _async_unskip actually confirms cleared --
            # a transient clear_skipped failure for one entity in the batch
            # must not lose track of it (see _async_unskip's own return
            # value).
            for (entity_id, _to_version), succeeded in zip(items, results):
                if succeeded:
                    del self._skipped[entity_id]
            await self._store.async_save(self._skipped)

    async def _async_evaluate_all(self) -> None:
        if not self._active:
            return
        # Serialized against every other pass -- see self._lock's own
        # comment for the exact race this closes (two overlapping passes
        # both touching self._skipped for the same entity while one's own
        # service call was still in flight).
        async with self._lock:
            # Every entity the coordinator currently tracks, plus any
            # leftover record for one that's since dropped out of the
            # cache entirely (e.g. the update entity disappeared) -- same
            # shape as install_manager.py's own tick, and for the same
            # reason: a leftover record with nothing to evaluate it
            # against just gets pruned instead of lingering in storage
            # forever. Concurrent *within* this one call, not one entity
            # at a time -- same reasoning as _async_clear_all above.
            entity_ids = set(self._coordinator.cache) | set(self._skipped)
            results = await asyncio.gather(*(self._async_evaluate_one(entity_id) for entity_id in entity_ids))
            dirty = any(results)
            if dirty:
                await self._store.async_save(self._skipped)

    async def _async_evaluate_one(self, entity_id: str) -> bool:
        cached = self._coordinator.cache.get(entity_id)
        recorded = self._skipped.get(entity_id)

        if cached is None:
            # No longer tracked at all -- nothing left to evaluate against,
            # just drop our own record if we had one.
            if recorded is not None:
                del self._skipped[entity_id]
                return True
            return False

        state = self.hass.states.get(entity_id)
        skipped_version = state.attributes.get("skipped_version") if state else None
        latest_version = cached["latest_version"]

        # A "ready" entity can still not actually be actionable right now if
        # it's waiting its turn behind a sibling device in a Zigbee rollout
        # queue, treated the same as a plain "waiting" status below, same
        # hide-until-actionable reasoning, same hide_postponed setting.
        if cached["status"] == "waiting" or self._rollout_manager.is_queued(entity_id):
            if recorded == latest_version:
                if skipped_version == latest_version:
                    return False  # still exactly as we left it
                # Cleared by something other than us since we skipped it
                # (the user un-skipping it themselves, most likely) --
                # respect that, don't re-skip it out from under them.
                del self._skipped[entity_id]
                return True
            if skipped_version == latest_version:
                # Already skipped, but not by us (no matching record) --
                # someone else's skip, not ours to manage either way.
                return False
            await self._async_skip(entity_id, latest_version)
            return True

        # Not "waiting" anymore (ready/blocked/etc) -- if we're the one who
        # skipped it, un-skip it now that it no longer needs to be hidden.
        # Only drop our own record if _async_unskip actually confirms it's
        # safe to (see its own return value) -- a failed clear_skipped call
        # must not lose track of an update that's still actually hidden.
        if recorded is not None:
            if await self._async_unskip(entity_id, recorded):
                del self._skipped[entity_id]
                return True
            return False
        return False

    async def _async_skip(self, entity_id: str, to_version: str) -> None:
        # Recorded *before* the service call, not after -- found live: the
        # entity's own state_changed event (what coordinator.py's
        # is_own_skip check actually runs on) is fired from inside
        # entity.async_skip() itself, and gets scheduled as a *separate*
        # task (hass.async_create_task, see coordinator.py's own
        # _handle_state_changed) rather than run inline -- so it can end up
        # processed before this coroutine ever resumes past its own
        # `await ... blocking=True` and reaches the assignment that used to
        # live here. That meant the coordinator sometimes saw no matching
        # record yet at the exact moment it mattered, and misclassified our
        # own automatic skip as a genuine user-initiated one (surfaced
        # under "Skipped" instead of staying "Postponed"). Rolled back
        # below if the service call itself actually fails.
        self._skipped[entity_id] = to_version
        try:
            await self.hass.services.async_call("update", "skip", {"entity_id": entity_id}, blocking=True)
        except Exception:
            _LOGGER.exception("Update Manager couldn't skip %s", entity_id)
            del self._skipped[entity_id]

    async def _async_unskip(self, entity_id: str, to_version: str) -> bool:
        """Returns whether our own record for this entity/version can now
        safely be dropped -- True if there's nothing left to do (already
        cleared by something else) or clear_skipped just succeeded; False
        only if the service call itself failed and skipped_version is still
        exactly what we set it to, so the record must be kept rather than
        silently losing track of an update that's still actually hidden
        (found live: the two used to be unconditionally paired, an
        unskip that failed still had its record deleted right after)."""
        state = self.hass.states.get(entity_id)
        # Only clear it if it's still actually set to the exact version we
        # skipped -- if the version already moved on, HA's own
        # state_attributes already cleared skipped_version itself
        # (confirmed against source), nothing left for us to do.
        if state is None or state.attributes.get("skipped_version") != to_version:
            return True
        try:
            await self.hass.services.async_call("update", "clear_skipped", {"entity_id": entity_id}, blocking=True)
        except Exception:
            _LOGGER.exception("Update Manager couldn't un-skip %s", entity_id)
            return False
        return True
