"""Registers Update Manager's own sidebar panel (Phase 2, see FUTURE.md) --
a plain custom element, no build step, same convention as this project's
sibling Lovelace cards (cover-media-card.js etc.), just loaded as a HA
sidebar panel instead of a dashboard card resource.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.components.panel_custom import async_register_panel
from homeassistant.core import HomeAssistant

from .const import DOMAIN

PANEL_URL_PATH = "update-manager"
_STATIC_URL_PATH = "/update_manager_panel"
_PANEL_DIR = Path(__file__).parent / "panel"
_PANEL_JS_PATH = _PANEL_DIR / "update-manager-panel.js"
_PANEL_REGISTERED = f"{DOMAIN}_panel_registered"


def _panel_js_cache_key() -> str:
    """A short hash of the panel JS file's own current content, not the
    integration's version string -- found live (2026-07-17): the file gets
    edited far more often, during ordinary development, than the version in
    manifest.json gets (or should get) bumped, and StaticPathConfig's own
    cache_headers=True below tells browsers to cache module_url
    aggressively/indefinitely. Without something that changes whenever the
    file's contents do, every single edit this session kept being served
    from the browser's cache until a hard refresh -- several "this doesn't
    seem to do anything" reports were really just stale JS still running."""
    return hashlib.sha256(_PANEL_JS_PATH.read_bytes()).hexdigest()[:12]


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
        module_url=f"{_STATIC_URL_PATH}/update-manager-panel.js?v={_panel_js_cache_key()}",
        embed_iframe=False,
        require_admin=True,
    )
