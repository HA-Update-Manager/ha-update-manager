"""Registers Update Manager's own sidebar panel (Phase 2, see FUTURE.md) --
a plain custom element, no build step, same convention as this project's
sibling Lovelace cards (cover-media-card.js etc.), just loaded as a HA
sidebar panel instead of a dashboard card resource.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from homeassistant.components.frontend import async_register_built_in_panel
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN

PANEL_URL_PATH = "update-manager"
_STATIC_URL_PATH = "/update_manager_panel"
_PANEL_DIR = Path(__file__).parent / "panel"
_PANEL_JS_PATH = _PANEL_DIR / "update-manager-panel.js"
_STATIC_PATH_REGISTERED = f"{DOMAIN}_static_path_registered"


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
    """Re-registers the panel with a fresh module_url on every call (e.g.
    every integration reload), not idempotent for that part anymore --
    found live, 2026-07-22: the previous version registered the panel
    exactly once per HA process (guarded the same way the static path
    registration below still is), which meant _panel_js_cache_key's own
    hash was captured a single time and then frozen until a full HA
    restart. Only a genuine process restart, not a reload and not a
    browser refresh, ever picked up a JS file change after that first
    registration -- during a long live-testing session this silently kept
    serving stale panel JS while looking, from the outside, exactly like
    "the fix didn't work".

    panel_custom.async_register_panel (the wrapper normally used for this)
    has no update path of its own -- it always raises ValueError on a
    second call for the same frontend_url_path -- so this calls
    frontend.async_register_built_in_panel directly instead, with
    update=True, replicating panel_custom's own config shape (verified
    against its real source, home-assistant/core stable tag 2026.7.3).

    The static path registration itself doesn't have this problem (the
    file is served fresh on every single request already, StaticPathConfig
    isn't a one-time snapshot); only registering the *route* needs to
    happen exactly once, so that part keeps its own separate guard."""
    if not hass.data.get(_STATIC_PATH_REGISTERED):
        hass.data[_STATIC_PATH_REGISTERED] = True
        await hass.http.async_register_static_paths(
            [StaticPathConfig(_STATIC_URL_PATH, str(_PANEL_DIR), True)]
        )

    async_register_built_in_panel(
        hass,
        component_name="custom",
        sidebar_title="Update Manager",
        sidebar_icon="mdi:update",
        frontend_url_path=PANEL_URL_PATH,
        config={
            "_panel_custom": {
                "name": "update-manager-panel",
                "embed_iframe": False,
                "trust_external": False,
                "module_url": f"{_STATIC_URL_PATH}/update-manager-panel.js?v={_panel_js_cache_key()}",
            }
        },
        require_admin=True,
        update=True,
    )
