from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, State, callback

from .const import DOMAIN
from .coordinator import UpdateManagerCoordinator, rules_from_options
from .install_log import InstallLog
from .websocket_api import async_setup_websocket_api

PLATFORMS: list[str] = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    rules = rules_from_options(dict(entry.options))
    coordinator = UpdateManagerCoordinator(hass, rules)
    await coordinator.async_start()

    install_log = InstallLog(hass)
    await install_log.async_load()

    @callback
    def _on_install(entity_id: str, old_version: str, new_version: str, new_state: State) -> None:
        hass.async_create_task(
            install_log.async_log_install(
                entity_id, old_version, new_version, release_url=new_state.attributes.get("release_url")
            )
        )

    coordinator.async_add_install_listener(_on_install)

    hass.data[DOMAIN] = {"coordinator": coordinator, "install_log": install_log}
    async_setup_websocket_api(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(update_listener))
    entry.async_on_unload(coordinator.async_stop)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data.pop(DOMAIN, None)
    return unloaded


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
