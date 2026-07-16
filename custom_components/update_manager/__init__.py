from __future__ import annotations

import asyncio

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, State, callback

from .const import DOMAIN
from .coordinator import UpdateManagerCoordinator, excluded_entities_from_options, rules_from_options
from .install_log import InstallLog
from .install_manager import InstallManager, auto_install_rules_from_options
from .panel import async_register_update_manager_panel
from .websocket_api import async_setup_websocket_api

PLATFORMS: list[str] = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    options = dict(entry.options)
    rules = rules_from_options(options)
    coordinator = UpdateManagerCoordinator(hass, rules, excluded_entities_from_options(options))
    install_log = InstallLog(hass)
    install_manager = InstallManager(hass, coordinator, auto_install_rules_from_options(options))

    # None of these three depend on another's result (install_manager only
    # needs the coordinator *object*, already passed in above, not its
    # finished scan) -- coordinator's own staggered bulk scan can take
    # several seconds on a large instance, and there's no reason the two
    # independent Store loads should wait behind it instead of running
    # alongside it.
    await asyncio.gather(
        coordinator.async_start(),
        install_log.async_load(),
        install_manager.async_load(),
    )

    @callback
    def _on_install(entity_id: str, old_version: str, new_version: str, new_state: State) -> None:
        hass.async_create_task(
            install_log.async_log_install(
                entity_id,
                old_version,
                new_version,
                release_url=new_state.attributes.get("release_url"),
                release_summary=new_state.attributes.get("release_summary"),
                supported_features=new_state.attributes.get("supported_features", 0),
            )
        )

    coordinator.async_add_install_listener(_on_install)
    install_manager.async_start()

    hass.data[DOMAIN] = {
        "coordinator": coordinator,
        "install_log": install_log,
        "install_manager": install_manager,
    }
    async_setup_websocket_api(hass)
    await async_register_update_manager_panel(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(update_listener))
    entry.async_on_unload(coordinator.async_stop)
    entry.async_on_unload(install_manager.async_stop)
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
    it from nothing."""
    data = hass.data.get(DOMAIN)
    if not data:
        return
    options = dict(entry.options)
    await data["coordinator"].async_update_rules(
        rules_from_options(options), excluded_entities_from_options(options)
    )
    data["install_manager"].update_rules(auto_install_rules_from_options(options))
