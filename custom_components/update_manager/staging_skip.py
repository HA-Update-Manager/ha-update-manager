"""Opt-in: while an update is still "waiting" (staging.py's own status, not yet
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
from homeassistant.helpers import entity_registry as er
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
        # entity_id -> the version _async_evaluate_one suspects (but hasn't
        # yet confirmed) got un-skipped by something other than this module
        # -- see that method's own comment on why a single observed
        # mismatch isn't trusted immediately.
        self._pending_clears: dict[str, str] = {}
        # entity_ids already warned about auto_update=True (see
        # _async_evaluate_one's own guard) -- a fixed, unchanging trait of
        # the entity, not something that would ever need re-warning about on
        # a later pass. Logged once per entity instead of not at all,
        # 2026-08-11 direct user feedback: staying fully silent about it
        # made "hide postponed updates" having no visible effect on this one
        # entity look unexplained rather than a known limitation.
        self._auto_update_warned: set[str] = set()
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
        # id(self)/id(self._skipped): a second StagingSkipManager instance
        # (e.g. a duplicate/leftover config entry) racing this one against
        # the same real entities and the same on-disk store would otherwise
        # be indistinguishable from a single-instance bug from this log
        # alone -- kept at DEBUG (invisible by default, enable per-user if
        # this class of postponed/skipped-misclassification bug ever
        # recurs) rather than removed outright.
        _LOGGER.debug(
            "Update Manager: [instance %s, dict %s] loaded %d own-skip record(s): %r",
            id(self),
            id(self._skipped),
            len(self._skipped),
            self._skipped,
        )

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
        recorded = self._skipped.get(entity_id)
        result = recorded == version
        if not result:
            # A genuine skip (skipped_version really set) not being
            # recognized as our own means this entity shows as Skipped
            # instead of Postponed -- kept at DEBUG for the same reasoning
            # async_load's own comment gives.
            _LOGGER.debug(
                "Update Manager: [instance %s, dict %s] %s has skipped_version == %s but no matching record "
                "(recorded=%r, current full dict=%r) -- showing as Skipped instead of Postponed",
                id(self),
                id(self._skipped),
                entity_id,
                version,
                recorded,
                self._skipped,
            )
        return result

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
        self._pending_clears.pop(entity_id, None)
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
            # Found live, 2026-08-10, via targeted diagnostic logging: right
            # after a restart, an MQTT-backed entity (Zigbee2MQTT's own
            # update entities in particular) can take
            # anywhere from seconds to minutes to report back in, well after
            # this module's own first evaluate_all pass already runs (see
            # async_start's own comment -- it fires right away, precisely so
            # a "waiting" update already skipped before the restart doesn't
            # sit unnecessarily visible in the meantime). Every entity_id
            # this module already has a record for is included in this same
            # pass's own entity_ids (see _async_evaluate_all), regardless of
            # whether the coordinator has it cached yet -- an entity that
            # simply hasn't reported in yet has no cache entry either, and
            # used to look identical to one genuinely gone for good, both
            # landing right here. Confirmed against a real diagnostics
            # session: several real, still-valid records for entities that
            # were merely slow to reconnect got deleted within seconds of
            # being loaded, this exact branch the only place that could.
            # Only truly gone warrants dropping the record -- checked
            # against the *entity registry*, not hass.states (found live,
            # 2026-08-10, right after shipping the hass.states version of
            # this same guard: two Zigbee2MQTT lamps that took noticeably
            # longer than their siblings to reconnect still lost their
            # record even though they were still genuinely reconnecting,
            # not gone. hass.states.get(entity_id) is None
            # both for an entity genuinely removed from Home Assistant *and*
            # for one that's registered but hasn't reported any state at all
            # yet -- indistinguishable from each other by that check alone,
            # and the latter is exactly the case this whole branch exists to
            # not misdiagnose. The entity registry entry itself, by
            # contrast, is created once and persists independently of
            # whether the entity's own integration is currently connected
            # or has reported in yet -- gone from *that* means genuinely
            # removed (integration uninstalled, entity deleted), which is
            # the only case this should ever act on.
            registry = er.async_get(self.hass)
            if recorded is not None and registry.async_get(entity_id) is None:
                del self._skipped[entity_id]
                self._pending_clears.pop(entity_id, None)
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
                    # Still exactly as we left it -- and no longer a
                    # suspected external clear either, see the mismatch
                    # branch below for why this needs clearing here too.
                    self._pending_clears.pop(entity_id, None)
                    return False
                # Found live, 2026-08-10, via the same entity-id-labelled
                # instance/dict-identity logging used to chase this bug
                # elsewhere in this file: a coordinator cache entry existing
                # with status "waiting" does *not* mean this entity has
                # finished restoring *all* of its own state after a restart
                # -- confirmed on real Alarmo/Zonneplan/Zigbee2MQTT entities,
                # latest_version/installed_version can already be populated
                # (enough for a "waiting" cache entry to exist at all) while
                # skipped_version specifically still lags behind, arriving
                # moments later over its own, slower path. A single mismatch
                # here used to be trusted immediately as "the user cleared
                # this themselves" and deleted our own, still-correct record
                # on the spot -- confirmed via that same logging: the record
                # was gone within 3 seconds of being loaded, for entities
                # that were both still present and still genuinely skipped
                # in real Home Assistant state moments later. Only acted on
                # once the *same* mismatch is still there on a *later* pass
                # (this module's own evaluate_all reruns on every coordinator
                # recompute, so a real, deliberate external clear is still
                # caught within moments, just not on the very first read) --
                # a transient restore-in-progress state naturally self-heals
                # before that second look ever happens.
                if self._pending_clears.get(entity_id) == latest_version:
                    del self._pending_clears[entity_id]
                    del self._skipped[entity_id]
                    return True
                self._pending_clears[entity_id] = latest_version
                return False
            if skipped_version == latest_version:
                # Already skipped, but not by us (no matching record) --
                # someone else's skip, not ours to manage either way.
                return False
            if state is not None and state.attributes.get("auto_update"):
                # HA's own update.skip service wrapper (homeassistant/
                # components/update/__init__.py's async_skip) unconditionally
                # rejects this for any entity with auto_update=True --
                # nothing this module could ever do makes that call succeed,
                # it's a fixed trait of the entity, not a transient state.
                # Found live, 2026-08-11: without this check, an entity
                # whose own integration republishes its state frequently
                # (each publish triggering another coordinator recompute,
                # another _on_recompute, another _async_evaluate_all pass)
                # retried and failed this same doomed call every couple of
                # seconds, 232 times in 5 minutes in one real log. hide_post-
                # poned simply can't hide this entity's own update count
                # contribution -- it stays visible in HA's native count like
                # any other auto_update entity, same as if this feature
                # didn't exist for it at all. Postponement/wait_days/
                # schedule/auto-install themselves are untouched by this --
                # only the "hide from HA's own count" half of the feature
                # can't apply here.
                if entity_id not in self._auto_update_warned:
                    self._auto_update_warned.add(entity_id)
                    _LOGGER.warning(
                        "Update Manager: %s has auto_update enabled, so its own integration "
                        "manages installs automatically -- 'hide postponed updates' can't hide "
                        "it from Home Assistant's own update count while postponed (postponement "
                        "itself still applies normally)",
                        entity_id,
                    )
                return False
            await self._async_skip(entity_id, latest_version)
            return True

        # Not "waiting" anymore (ready/blocked/etc) -- if we're the one who
        # skipped it, un-skip it now that it no longer needs to be hidden.
        # Only drop our own record if _async_unskip actually confirms it's
        # safe to (see its own return value) -- a failed clear_skipped call
        # must not lose track of an update that's still actually hidden.
        if recorded is not None:
            # An own-skip whose staging wait period elapses
            # (cached["status"] leaves "waiting") lands here and gets
            # actively un-skipped -- if that real clear_skipped call
            # doesn't stick for some entities (or its own resulting
            # state_changed doesn't propagate), the record still gets
            # dropped below regardless. Kept at DEBUG for the same
            # reasoning async_load's own comment gives.
            _LOGGER.debug(
                "Update Manager: %s no longer 'waiting' (status=%r, recorded=%r) -- un-skipping",
                entity_id,
                cached["status"],
                recorded,
            )
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
        # below if the service call itself actually fails -- but only if
        # it actually didn't take effect.
        self._skipped[entity_id] = to_version
        try:
            await self.hass.services.async_call("update", "skip", {"entity_id": entity_id}, blocking=True)
        except Exception:
            _LOGGER.exception("Update Manager couldn't skip %s", entity_id)
            # Found by review: an exception here doesn't necessarily mean
            # nothing happened -- an integration's own async_skip() can
            # legitimately write skipped_version and *then* raise on some
            # later step in that same call. Blindly deleting the record
            # regardless left a genuinely-skipped entity with no record at
            # all, so the very next state_changed/recheck saw
            # skipped_version already matching but is_own_skip() now
            # returning False -- misclassified as a real, user-initiated
            # skip (surfaced as "Skipped" instead of staying "Postponed")
            # for something Update Manager itself just skipped. Same
            # "check the real state before deciding" fix _async_unskip
            # below already needed once for its own, symmetric version of
            # this exact mistake.
            state = self.hass.states.get(entity_id)
            if not (state is not None and state.attributes.get("skipped_version") == to_version):
                del self._skipped[entity_id]
        # Saved here, immediately, not left to _async_evaluate_all's own
        # batched "if dirty" save at the end of the whole concurrent pass
        # -- found live, 2026-08-10: every postponed
        # update showed as "Skipped" after a restart, with nothing in the
        # logs. Root cause: the real skip above had already genuinely
        # taken effect in HA's own (reliably persisted) entity state, but
        # this module's own ownership record for it lived only in memory
        # until the *whole batch* finished and got saved -- a restart
        # landing anywhere in that window (this session alone restarted
        # HA many times while testing) lost the record entirely, even
        # though the real skip survived fine. Cheap enough to do per call:
        # this only ever runs for a genuine skip/unskip action, not a hot
        # path, and correctness here is worth far more than batching a
        # handful of writes into one.
        await self._store.async_save(self._skipped)
        # Kept at DEBUG for the same reasoning async_load's own comment gives.
        _LOGGER.debug(
            "Update Manager: [instance %s] skipped %s for %s, record now %r, saved",
            id(self),
            entity_id,
            to_version,
            self._skipped.get(entity_id),
        )

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
        # Found live, 2026-08-10, via targeted diagnostic logging on this
        # exact spot: `blocking=True` only waits for the service handler's
        # own coroutine to finish, not for skipped_version to actually
        # change -- for an MQTT-backed entity (confirmed on real Zigbee2MQTT
        # devices) that attribute can genuinely update a moment later, once
        # a round-trip to the bridge completes, rather than synchronously
        # inside the handler the way most integrations' own skip/unskip
        # does. The old code trusted a successful call as proof the record
        # was safe to drop -- concretely traced to several real "Postponed"
        # updates silently losing their own ownership record and
        # reappearing as "Skipped" days later, with no matching is_own_skip
        # warning anywhere near the moment it actually happened, because the
        # drop occurred right here, straight after a "successful" call whose
        # effect just hadn't landed yet. Only ever report success once the
        # real state confirms it -- same "verify, don't trust" fix this
        # method's own docstring already describes once for the symmetric
        # failure case. A false negative here (this fires right as the
        # delayed update is about to land) just keeps the record one
        # evaluate_all pass longer than strictly needed, no worse than that.
        after = self.hass.states.get(entity_id)
        cleared = after is None or after.attributes.get("skipped_version") != to_version
        if not cleared:
            # Kept at DEBUG for the same reasoning async_load's own comment
            # gives -- this is the propagation-lag case that comment's own
            # docstring already expects, not itself evidence of a bug.
            _LOGGER.debug(
                "Update Manager: clear_skipped(%s) returned but skipped_version is still %r -- "
                "keeping our own record instead of trusting the call",
                entity_id,
                to_version,
            )
        return cleared
