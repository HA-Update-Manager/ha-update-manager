from __future__ import annotations

import asyncio

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, State, callback

from .const import CONF_ENABLED, CONF_HIDE_POSTPONED, DOMAIN
from .coordinator import UpdateManagerCoordinator, excluded_entities_from_options, rules_from_options
from .install_log import InstallLog
from .install_manager import InstallManager, auto_install_rules_from_options
from .panel import async_register_update_manager_panel
from .staging_skip import StagingSkipManager
from .websocket_api import async_apply_options, async_setup_websocket_api

PLATFORMS: list[str] = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    options = dict(entry.options)
    rules = rules_from_options(options)
    coordinator = UpdateManagerCoordinator(hass, rules, excluded_entities_from_options(options))
    install_log = InstallLog(hass)
    install_manager = InstallManager(hass, coordinator, auto_install_rules_from_options(options))
    staging_skip_manager = StagingSkipManager(hass, coordinator)
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
    )

    @callback
    def _on_install(entity_id: str, old_version: str, new_version: str, new_state: State) -> None:
        # Evaluated synchronously, right here, not inside the task below:
        # was_auto_installed() consumes (pops) install_manager's own record
        # of what it just dispatched, so it must be read at the moment this
        # callback fires, not whenever the scheduled task happens to run.
        auto_installed = install_manager.was_auto_installed(entity_id, new_version)
        hass.async_create_task(
            install_log.async_log_install(
                entity_id,
                old_version,
                new_version,
                release_url=new_state.attributes.get("release_url"),
                release_summary=new_state.attributes.get("release_summary"),
                supported_features=new_state.attributes.get("supported_features", 0),
                auto_installed=auto_installed,
            )
        )

    coordinator.async_add_install_listener(_on_install)
    install_manager.async_start()
    staging_skip_manager.async_start(bool(options.get(CONF_HIDE_POSTPONED, False)))

    hass.data[DOMAIN] = {
        "coordinator": coordinator,
        "install_log": install_log,
        "install_manager": install_manager,
        "staging_skip_manager": staging_skip_manager,
    }
    async_setup_websocket_api(hass)
    await async_register_update_manager_panel(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(update_listener))
    entry.async_on_unload(coordinator.async_stop)
    entry.async_on_unload(install_manager.async_stop)
    entry.async_on_unload(staging_skip_manager.async_stop)
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
