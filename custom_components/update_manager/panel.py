"""Registers Update Manager's own sidebar panel (Phase 2, see FUTURE.md) --
a plain custom element, no build step, same convention as this project's
sibling Lovelace cards (cover-media-card.js etc.), just loaded as a HA
sidebar panel instead of a dashboard card resource.
"""
from __future__ import annotations

from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.components.panel_custom import async_register_panel
from homeassistant.core import HomeAssistant

from .const import DOMAIN

PANEL_URL_PATH = "update-manager"
_STATIC_URL_PATH = "/update_manager_panel"
_PANEL_DIR = Path(__file__).parent / "panel"
_PANEL_REGISTERED = f"{DOMAIN}_panel_registered"


async def async_register_update_manager_panel(hass: HomeAssistant) -> None:
    """Idempotent: safe to call again on entry reload (e.g. after saving
    settings) -- registering the same frontend_url_path twice raises."""
    if hass.data.get(_PANEL_REGISTERED):
        return
    hass.data[_PANEL_REGISTERED] = True

    await hass.http.async_register_static_paths(
        [StaticPathConfig(_STATIC_URL_PATH, str(_PANEL_DIR), True)]
    )
    await async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name="update-manager-panel",
        sidebar_title="Update Manager",
        sidebar_icon="mdi:update",
        module_url=f"{_STATIC_URL_PATH}/update-manager-panel.js",
        embed_iframe=False,
        require_admin=True,
    )
