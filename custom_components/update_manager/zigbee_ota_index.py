"""Fetches and caches zigpy-ota's own native OTA index (zigpy_v2_ota.json,
the "firmwares" list inside it) -- the data zigbee_ota_release_notes.py
matches against. Chosen over the also-published Zigbee2MQTT-compatible
z2m_v1_ota.json: confirmed against zigpy-ota's own README, zigpy_v2 is what
zigpy/Home Assistant itself actually consumes, its manufacturer_names/
model_names fields are real lists (the z2m format splits one image with two
applicable models into two separate, duplicate-looking entries instead), and
it retains every real historical version per device, not just the newest
(confirmed live, 2026-11-13: a real multi-version Sonoff plug history, 5
entries, present in zigpy_v2 but collapsed to just the latest one in the
z2m-format export).

The exact download URL isn't hardcoded to a fixed path: zigpy-ota's own
README recommends discovering it through release/version/{channel}.json
first (confirmed live: the stable channel's own zigpy_v2 entry currently
points at a version-pinned GitHub Releases asset URL, not the "release/
files/stable/..." path this module used before switching to this discovery
step) -- that pinned-per-release shape is also why this module doesn't try
to cache *that* across restarts: a new zigpy-ota release simply means a new
URL to discover next time, nothing to invalidate.

Refetched at most every _REFRESH_INTERVAL: this index only grows when a new
firmware image is merged into zigpy-ota, never more than a few times a day
project-wide, so there's no reason to fetch it on every dialog open.

A bare module-level cache (no config entry involved, nothing to persist
across a restart), same "harmless, process-lifetime-only" scope as the
panel's own _deviceIdentityCache. Kept out of UpdateManagerData deliberately:
every other manager there is either stateful config or needs hass at
construction time, neither of which applies to a single shared HTTP cache.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

_VERSION_DISCOVERY_URL = "https://raw.githubusercontent.com/zigpy/zigpy-ota/release/version/stable.json"
_REFRESH_INTERVAL = timedelta(hours=6)


async def _async_fetch_firmwares(hass: HomeAssistant) -> list[dict[str, Any]] | None:
    """The current zigpy_v2 index's own "firmwares" list, or None on any
    failure (a bad discovery response, a missing/malformed schema entry, a
    network error, an unexpected top-level shape) -- never raises, same
    graceful treatment as the rest of this fallback."""
    session = async_get_clientsession(hass)
    try:
        async with session.get(_VERSION_DISCOVERY_URL, timeout=15) as response:
            if response.status != 200:
                return None
            discovery = await response.json()
        index_url = discovery.get("schemas", {}).get("zigpy_v2", {}).get("url")
        if not index_url:
            return None
        async with session.get(index_url, timeout=15) as response:
            if response.status != 200:
                return None
            data = await response.json()
    except Exception:
        _LOGGER.debug("Couldn't fetch zigpy-ota's own native OTA index", exc_info=True)
        return None
    firmwares = data.get("firmwares") if isinstance(data, dict) else None
    return firmwares if isinstance(firmwares, list) else None


class _ZigbeeOtaIndexCache:
    def __init__(self) -> None:
        self._data: list[dict[str, Any]] | None = None
        self._cached_at: Any = None
        self._lock = asyncio.Lock()

    async def async_get(self, hass: HomeAssistant) -> list[dict[str, Any]]:
        """The cached index, refetching first if it's missing or stale.
        Returns whatever was last fetched successfully (possibly still
        empty, on a first-ever failure) rather than raising -- same
        graceful "nothing to add" treatment as every other release-notes
        enrichment in this project; a transient network hiccup must never
        break the dialog's own release-notes section over what is, at
        best, a nice-to-have fallback."""
        async with self._lock:
            if (
                self._data is not None
                and self._cached_at is not None
                and dt_util.utcnow() - self._cached_at < _REFRESH_INTERVAL
            ):
                return self._data
            firmwares = await _async_fetch_firmwares(hass)
            if firmwares is not None:
                self._data = firmwares
                self._cached_at = dt_util.utcnow()
        return self._data or []


_INDEX_CACHE = _ZigbeeOtaIndexCache()


async def async_get_zigbee_ota_index(hass: HomeAssistant) -> list[dict[str, Any]]:
    return await _INDEX_CACHE.async_get(hass)
