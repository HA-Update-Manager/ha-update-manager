from __future__ import annotations

import asyncio

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, State, callback

from .community_verdict import CommunityVerdictManager
from .const import CONF_ENABLED, CONF_HIDE_POSTPONED, DOMAIN
from .coordinator import (
    UpdateManagerCoordinator,
    excluded_entities_from_options,
    rules_from_options,
    trusted_voters_from_options,
)
from .github_auth import GitHubAuthManager
from .install_log import InstallLog
from .install_manager import InstallManager, auto_install_rules_from_options
from .my_votes import MyVotesManager
from .panel import async_register_update_manager_panel
from .rollout_manager import RolloutManager
from .staging_skip import StagingSkipManager
from .websocket_api import async_apply_options, async_setup_websocket_api

PLATFORMS: list[str] = ["sensor", "switch"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
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
    await asyncio.gather(
        coordinator.async_start(),
        install_log.async_load(),
        install_manager.async_load(),
        rollout_manager.async_load(),
        community_verdict_manager.async_load(),
        github_auth_manager.async_load(),
        my_votes_manager.async_load(),
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
                release_summary=new_state.attributes.get("release_summary"),
                supported_features=new_state.attributes.get("supported_features", 0),
                auto_installed=context is not None,
                auto_install_reason=reason,
                trusted_voter_usernames=trusted_voter_usernames,
                announced_at=announced_at,
                available_since=cached.get("available_since") if cached else None,
            )
        )

    coordinator.async_add_install_listener(_on_install)
    install_manager.async_start()
    staging_skip_manager.async_start(bool(options.get(CONF_HIDE_POSTPONED, True)))
    rollout_manager.async_start()

    hass.data[DOMAIN] = {
        "coordinator": coordinator,
        "install_log": install_log,
        "install_manager": install_manager,
        "staging_skip_manager": staging_skip_manager,
        "rollout_manager": rollout_manager,
        "community_verdict_manager": community_verdict_manager,
        "github_auth_manager": github_auth_manager,
        "my_votes_manager": my_votes_manager,
    }
    async_setup_websocket_api(hass)
    await async_register_update_manager_panel(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(update_listener))
    entry.async_on_unload(coordinator.async_stop)
    entry.async_on_unload(install_manager.async_stop)
    entry.async_on_unload(staging_skip_manager.async_stop)
    entry.async_on_unload(rollout_manager.async_stop)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data.pop(DOMAIN, None)
    return unloaded


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Applies newly-saved settings in place, not via a full entry reload
    (changed 2026-07-16): a rules-only change doesn't need the coordinator's
    cache rebuilt from scratch (a multi-second, recorder-querying bulk
    scan) -- found live, the Updates/History tabs briefly went empty after
    every settings save while the old reload-based approach was rebuilding
    it from nothing. Shares its actual application logic with
    websocket_api.py's own save_settings handler (async_apply_options) --
    see that function's own docstring."""
    await async_apply_options(hass, dict(entry.options))
