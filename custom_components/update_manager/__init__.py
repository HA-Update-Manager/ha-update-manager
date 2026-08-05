from __future__ import annotations

import asyncio

from homeassistant.core import HomeAssistant, State, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_integration

from .community_verdict import CommunityVerdictManager
from .const import (
    CONF_ENABLED,
    CONF_HIDE_POSTPONED,
    CONF_LARGE_AUTO_INSTALL,
    CONF_LARGE_WAIT_DAYS,
    DOMAIN,
    EVENT_INSTALLED,
)
from .coordinator import (
    UpdateManagerCoordinator,
    excluded_entities_from_options,
    rules_from_options,
    trusted_voters_from_options,
)
from .device import device_info as update_manager_device_info
from .github_auth import GitHubAuthManager
from .install_log import InstallLog
from .install_manager import InstallManager, auto_install_rules_from_options
from .my_votes import MyVotesManager
from .panel import async_register_update_manager_panel
from .rollout_manager import RolloutManager
from .runtime_data import UpdateManagerConfigEntry, UpdateManagerData
from .staging_skip import StagingSkipManager
from .websocket_api import async_apply_options, async_setup_websocket_api

PLATFORMS: list[str] = ["sensor", "switch"]

_ENABLED_SWITCH_UNIQUE_ID = f"{DOMAIN}_enabled"
_ENABLED_SWITCH_NEW_ENTITY_ID = "switch.update_manager"


def _migrate_enabled_switch_entity_id(hass: HomeAssistant) -> None:
    """One-time rename of the master switch's own entity_id, from
    switch.update_manager_enabled to switch.update_manager -- direct user
    feedback, 2026-08-07: now that the switch is the device's own unnamed
    primary entity (see switch.py's own docstring), its entity_id should
    read as plainly as the device itself, not carry a now-redundant
    "_enabled" suffix.

    unique_id itself is unchanged (still _ENABLED_SWITCH_UNIQUE_ID) -- only
    entity_id moves. That matters: entity_id doesn't follow a name/
    translation_key change on its own once an entity already exists (only
    freshly-created entities get one derived from the current name), so
    without this, every install that set this integration up before this
    device existed would keep the old entity_id forever, silently
    diverging from a fresh install's own switch.update_manager. Renaming
    the *same* registry row (not creating a new entity) also means
    anything already tied to it, like an entity customization or long-term
    statistics, follows along instead of being orphaned.

    Safe to run on every startup: a no-op once the rename has already
    happened, since the old entity_id simply won't be found anymore after
    that. Runs before platform setup, but doesn't strictly need to --
    entity_registry entries persist independently of whether their entity
    is currently loaded."""
    registry = er.async_get(hass)
    old_entity_id = registry.async_get_entity_id("switch", DOMAIN, _ENABLED_SWITCH_UNIQUE_ID)
    if old_entity_id is None or old_entity_id == _ENABLED_SWITCH_NEW_ENTITY_ID:
        return
    if registry.async_get(_ENABLED_SWITCH_NEW_ENTITY_ID) is not None:
        # Something else already claimed the new id -- shouldn't normally
        # happen for a single-instance integration's own bare-domain id,
        # but never silently clobber a different, unrelated entity over
        # this cosmetic rename.
        return
    registry.async_update_entity(old_entity_id, new_entity_id=_ENABLED_SWITCH_NEW_ENTITY_ID)


# Old option key -> new one, for the "big"->"large" size rename (direct user
# feedback, 2026-08-07, same conversation as the switch rename above: "large"
# reads as a plain size next to small/medium, where "big" read more like a
# judgment call about the update itself rather than the size of its version
# jump).
_OLD_TO_NEW_OPTION_KEYS = {
    "big_wait_days": CONF_LARGE_WAIT_DAYS,
    "big_auto_install": CONF_LARGE_AUTO_INSTALL,
}


def _migrate_large_size_option_keys(hass: HomeAssistant, entry: UpdateManagerConfigEntry) -> None:
    """One-time rename of the two stored option keys for the former "big"
    size, now "large" -- without this, every existing install would have its
    real, deliberately-saved wait/auto-install choice for that size silently
    discarded the moment the const.py keys changed, quietly falling back to
    DEFAULT_WAIT_DAYS's own large_wait_days default (7 days, no
    auto-install) instead, with no warning that a customization was lost.

    Renames the *keys* only, preserving whatever value was already saved.
    Safe to run on every startup: a no-op once the old keys are gone. Must
    run before `options = dict(entry.options)` below reads them into the
    rules this same setup builds."""
    options = dict(entry.options)
    changed = False
    for old_key, new_key in _OLD_TO_NEW_OPTION_KEYS.items():
        if old_key in options:
            # setdefault, not a plain overwrite -- if the new key
            # somehow already has a value (shouldn't normally happen),
            # never clobber it, just drop the now-redundant old one.
            options.setdefault(new_key, options.pop(old_key))
            changed = True
    if changed:
        hass.config_entries.async_update_entry(entry, options=options)


async def async_setup_entry(hass: HomeAssistant, entry: UpdateManagerConfigEntry) -> bool:
    _migrate_large_size_option_keys(hass, entry)
    options = dict(entry.options)
    rules = rules_from_options(options)
    # Constructed before the coordinator: it takes a reference to this (see
    # community_verdict.py's own docstring), and this manager itself needs
    # nothing but hass, so there's no reason to reach for a setter/callback
    # like rollout_manager.py's own set_recently_executed_setter does for a
    # genuine two-way dependency.
    community_verdict_manager = CommunityVerdictManager(hass)
    # Set once, here, before coordinator.async_start()'s own initial bulk
    # scan below picks it up for the very first refresh -- same reasoning/
    # timing as coordinator.set_master_enabled further down. Re-applied by
    # async_apply_options on every settings save, no reload needed either.
    community_verdict_manager.set_trusted_voters(trusted_voters_from_options(options))
    # Same reasoning as community_verdict_manager just above: needs only
    # hass, nothing else holds a reference into it (yet, a future voting
    # feature will read it for a valid access token, not the other way
    # around), so no setter/callback wiring needed here either.
    github_auth_manager = GitHubAuthManager(hass)
    # Same reasoning again: needs only hass, read by websocket_api.py's own
    # verdict_for_version handler, written by its vote handler.
    my_votes_manager = MyVotesManager(hass)
    coordinator = UpdateManagerCoordinator(hass, rules, excluded_entities_from_options(options), community_verdict_manager)
    install_log = InstallLog(hass)
    # Constructed before InstallManager/StagingSkipManager: both take a
    # reference to it (see rollout_manager.py's own docstring: gates every
    # install dispatch, and staging_skip.py hides a queued entry the same
    # way it already hides a plain "waiting" one).
    rollout_manager = RolloutManager(hass, coordinator)
    install_manager = InstallManager(hass, coordinator, auto_install_rules_from_options(options), rollout_manager)
    staging_skip_manager = StagingSkipManager(hass, coordinator, rollout_manager)
    # The reverse direction: only wireable once install_manager exists, see
    # rollout_manager.py's own set_recently_executed_setter docstring for
    # why this is a setter/callback rather than a constructor argument on
    # either side (avoids an import cycle between the two modules).
    rollout_manager.set_recently_executed_setter(install_manager.mark_recently_executed)
    # Same reasoning, see rollout_manager.py's own set_failure_handler
    # docstring: a queued entry's install can fail too, once this module is
    # the one dispatching it, and it needs the exact same cleanup/
    # notification install_manager.py's own non-queued path already has.
    rollout_manager.set_failure_handler(install_manager.handle_install_failure)
    # The single shared master-enabled flag (see coordinator.py's own
    # set_master_enabled) -- set once, here, before either manager's
    # async_start() runs; both read it directly off the coordinator from
    # then on, no separate copy of their own to keep in sync.
    coordinator.set_master_enabled(bool(options.get(CONF_ENABLED, True)))
    # Wired up before coordinator.async_start()'s own initial bulk scan
    # below, not after -- so even the very first refresh of an entity
    # already skipped by us (e.g. a restart with an existing skip in
    # place) correctly reads as "postponed", not "skipped", from the
    # start.
    coordinator.set_own_skip_checker(staging_skip_manager.is_own_skip)

    # staging_skip_manager.async_load() awaited on its own, *before*
    # coordinator.async_start() -- found live (well, found by review, not
    # yet live): wiring the checker above doesn't actually guarantee its
    # data is ready. coordinator.async_start()'s bulk-scan loop calls
    # _async_refresh_one for its first entity with no `await` beforehand,
    # so if that first entity happens to be one this module auto-skipped
    # in a previous run, is_own_skip would run against a still-empty
    # self._skipped (async_load() hadn't even started yet inside the same
    # asyncio.gather) and misclassify it as a genuine user skip. A single
    # Store read is cheap -- not worth serializing the other three (the
    # coordinator's own staggered bulk scan is the actual slow part on a
    # large instance) behind it too.
    await staging_skip_manager.async_load()
    # install_log.async_load() *and* community_verdict_manager.async_load()
    # specifically (not the other three loads below) must both finish
    # before coordinator.async_start() -- install_log for the reason given
    # at _on_install's own registration further down, community_verdict_manager
    # because coordinator.py's own _async_cache_active reads
    # CommunityVerdictManager.peek_cached_verdict/peek_cached_trusted_vote
    # synchronously, straight from its in-memory cache, during the bulk
    # scan async_start() itself runs -- found by code review, 2026-07-27:
    # gathering it concurrently with async_start() again (an earlier
    # efficiency fix) reintroduced exactly the kind of race this whole
    # split was meant to avoid, just for a different manager: whichever
    # entities the scan reaches before this Store read resolves would
    # silently get None/empty community-verdict data for a moment, even
    # though a persisted cache exists on disk. install_manager/
    # rollout_manager/github_auth_manager have no such ordering dependency
    # and stay gathered together with coordinator.async_start() itself.
    # integration fetched alongside the other two here purely for
    # efficiency (see this gather's own docstring above for why install_log/
    # community_verdict_manager specifically can't just join
    # coordinator.async_start()'s own gather further down) -- fetching the
    # manifest.json version has no ordering dependency on anything else at
    # all, so it's free to run concurrently with them.
    _, _, integration = await asyncio.gather(
        install_log.async_load(), community_verdict_manager.async_load(), async_get_integration(hass, DOMAIN)
    )

    @callback
    def _on_install(entity_id: str, old_version: str, new_version: str, new_state: State) -> None:
        # Evaluated synchronously, right here, not inside the task below:
        # was_auto_installed() consumes (pops) install_manager's own record
        # of what it just dispatched, so it must be read at the moment this
        # callback fires, not whenever the scheduled task happens to run.
        # Same reasoning for reading coordinator.cache here rather than
        # inside the task: verified live 2026-07-23, this install-listener
        # fires synchronously from coordinator.py's own _handle_state_changed,
        # strictly before its own cache recompute (a separate, scheduled
        # task) has a chance to run, so this entity's cache entry still
        # reflects the version that just finished installing, in particular
        # its own available_since.
        context = install_manager.was_auto_installed(entity_id, new_version)
        reason = context.reason if context else None
        trusted_voter_usernames = context.trusted_voter_usernames if context else None
        announced_at = context.announced_at.isoformat() if context and context.announced_at else None
        cached = coordinator.cache.get(entity_id)
        hass.async_create_task(
            install_log.async_log_install(
                entity_id,
                old_version,
                new_version,
                release_url=new_state.attributes.get("release_url"),
                supported_features=new_state.attributes.get("supported_features", 0),
                auto_installed=context is not None,
                auto_install_reason=reason,
                trusted_voter_usernames=trusted_voter_usernames,
                announced_at=announced_at,
                available_since=cached.get("available_since") if cached else None,
            )
        )
        # See const.py's own EVENT_ANNOUNCED docstring for the events
        # design overall. Fired for every completed install, auto or
        # manual alike -- same "this is the one unified place an install
        # is confirmed done" reasoning install_log.py's own entry above
        # already relies on, not a second, separately-tracked notion of
        # "installed".
        hass.bus.async_fire(
            EVENT_INSTALLED,
            {
                "entity_id": entity_id,
                "from_version": old_version,
                "to_version": new_version,
                "auto_installed": context is not None,
                "auto_install_reason": reason,
                "trusted_voter_usernames": trusted_voter_usernames or [],
            },
        )

    # Registered, and install_log's own persisted entries loaded above,
    # *before* coordinator.async_start() below -- changed 2026-07-27:
    # that call's own bulk scan can now retroactively fire this exact
    # listener, synchronously, inline, for an install that completed
    # entirely while HA was down (see coordinator.py's own
    # _recover_install_across_restart), not only from a later live
    # state_changed event like before. install_log.async_load() had to be
    # pulled out of the gather below and awaited on its own first for this
    # reason: if it hadn't finished loading yet, _on_install's own
    # async_log_install would append to (and then save) an empty in-memory
    # list, silently wiping out every previously-logged install.
    coordinator.async_add_install_listener(_on_install)
    # The other three loads have no such ordering dependency on
    # coordinator.async_start() -- gathered together with it, not awaited
    # in front of it, so they still overlap with the coordinator's own
    # slow, staggered bulk scan the same way they did before install_log/
    # community_verdict_manager needed to move out on their own above.
    await asyncio.gather(
        coordinator.async_start(),
        install_manager.async_load(),
        rollout_manager.async_load(),
        github_auth_manager.async_load(),
        my_votes_manager.async_load(),
    )
    install_manager.async_start()
    staging_skip_manager.async_start(bool(options.get(CONF_HIDE_POSTPONED, True)))
    rollout_manager.async_start()

    entry.runtime_data = UpdateManagerData(
        coordinator=coordinator,
        install_log=install_log,
        install_manager=install_manager,
        staging_skip_manager=staging_skip_manager,
        rollout_manager=rollout_manager,
        community_verdict_manager=community_verdict_manager,
        github_auth_manager=github_auth_manager,
        my_votes_manager=my_votes_manager,
        integration_version=str(integration.version),
    )

    # A single virtual device for every one of this integration's own
    # entities to attach to (see device.py's own docstring) -- registered
    # explicitly here (rather than relying on whichever entity happens to
    # be set up first) so it exists before any platform below creates an
    # entity that references it.
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(config_entry_id=entry.entry_id, **update_manager_device_info(entry))
    _migrate_enabled_switch_entity_id(hass)

    async_setup_websocket_api(hass)
    await async_register_update_manager_panel(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(update_listener))
    entry.async_on_unload(coordinator.async_stop)
    entry.async_on_unload(install_manager.async_stop)
    entry.async_on_unload(staging_skip_manager.async_stop)
    entry.async_on_unload(rollout_manager.async_stop)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: UpdateManagerConfigEntry) -> bool:
    # Reset on success, found by code review, 2026-07-29: unlike the old
    # hass.data.pop(DOMAIN, None) this replaced, nothing was clearing
    # runtime_data itself back to None after an unload. websocket_api.py's
    # own _get_entry resolves the entry via hass.config_entries.async_entries,
    # which returns it regardless of load state, so _get_data would still
    # return the stale, already-stopped UpdateManagerData from before the
    # unload instead of None -- any websocket call arriving during that
    # window (e.g. from a panel tab left open) would silently operate on
    # managers whose own async_stop already ran, instead of hitting the
    # "not set up" guard every handler already has for the genuinely
    # pre-setup case.
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        entry.runtime_data = None
    return unloaded


async def update_listener(hass: HomeAssistant, entry: UpdateManagerConfigEntry) -> None:
    """Applies newly-saved settings in place, not via a full entry reload
    (changed 2026-07-16): a rules-only change doesn't need the coordinator's
    cache rebuilt from scratch (a multi-second, recorder-querying bulk
    scan) -- found live, the Updates/History tabs briefly went empty after
    every settings save while the old reload-based approach was rebuilding
    it from nothing. Shares its actual application logic with
    websocket_api.py's own save_settings handler (async_apply_options) --
    see that function's own docstring."""
    await async_apply_options(hass, dict(entry.options))
