"""Reads (and, via firmware_version_submit.py, contributes to) a
crowd-sourced {raw OTA integer -> real firmware version string} mapping per
device model, from the same community-votes repo as the voting feature:
https://github.com/HA-Update-Manager/community-votes.

Mirrors community_verdict.py's own two-tier peek/refresh shape (a
synchronous, no-fetch peek for a hot path, an async background refresh that
actually hits the network), but much simpler: no identity resolution, no
trusted voters, just a flat {raw_version: real_version} dict per
"manufacturer/model" key, read straight off
`firmware-versions/<manufacturer>/<model>.json` -- see that file's own
README in the community-votes repo for why one file per model rather than
one per raw version.

No manual URL-encoding of manufacturer/model here, matching
community_verdict.py's own unencoded `to_version_path` construction for the
"devices" category (which already reads real, space-containing paths like
"Hue Filament Globe Ambiance E27" successfully in production) -- aiohttp/yarl
handles the encoding itself. model *is* slugified though (see
slugify_zigbee_model), the one difference from that "devices" path: found
live, 2026-11-24, a model_id containing "/" was still being fetched here at
its own unslugified, nested path -- always empty, since
process-firmware-version.yml slugifies the identical way before ever
writing (added the same day, for the identical reason: "/" is both part of
the value and a path's own separator), so this household could never see
its own already-written data for that one model, forever looking new on
every refresh."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .community_votes_api import async_fetch_public_json
from .const import DOMAIN
from .zigbee import slugify_zigbee_model

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_firmware_versions"

FIRMWARE_VERSIONS_REPO_RAW_BASE = "https://raw.githubusercontent.com/HA-Update-Manager/community-votes/main"

# Same cadence as community_verdict.py's own _REFRESH_INTERVAL, for
# consistency -- bounds real request volume to at most one GET per distinct
# (manufacturer, model) pair this household owns, at most once an hour,
# regardless of how often the coordinator itself ticks.
_REFRESH_INTERVAL = timedelta(hours=1)


def _cache_key(manufacturer: str, model: str) -> str:
    return f"{manufacturer}/{model}"


class FirmwareVersionManager:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store: Store[dict[str, dict[str, Any]]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        # "manufacturer/model" -> {"versions": {"<raw>": "<real>", ...}, "fetched_at": iso}
        self._cache: dict[str, dict[str, Any]] = {}

    async def async_load(self) -> None:
        self._cache = await self._store.async_load() or {}

    def peek_cached_versions(self, manufacturer: str, model: str) -> dict[str, str]:
        """Whatever's currently cached for this model, stale or not, or {}
        if never fetched -- no network, safe for a hot path, same reasoning
        as community_verdict.py's own peek_cached_verdict."""
        record = self._cache.get(_cache_key(manufacturer, model))
        return record.get("versions", {}) if record else {}

    def _fresh_cached(self, key: str) -> bool:
        record = self._cache.get(key)
        if record is None:
            return False
        fetched_at = dt_util.parse_datetime(record.get("fetched_at", ""))
        return fetched_at is not None and dt_util.utcnow() - fetched_at < _REFRESH_INTERVAL

    async def async_get_versions(self, manufacturer: str, model: str, *, force: bool = False) -> dict[str, str]:
        key = _cache_key(manufacturer, model)
        if not force and self._fresh_cached(key):
            return self._cache[key].get("versions", {})

        try:
            payload = await async_fetch_public_json(
                self.hass,
                f"{FIRMWARE_VERSIONS_REPO_RAW_BASE}/firmware-versions/{manufacturer}/{slugify_zigbee_model(model)}.json",
            )
        except Exception:
            # Transient (timeout, 5xx, DNS hiccup): falls back to whatever
            # was last known for this model instead of blanking it, same
            # graceful-degradation reasoning as community_verdict.py's own
            # async_get_verdict.
            _LOGGER.debug("Couldn't fetch firmware versions for %s/%s", manufacturer, model, exc_info=True)
            record = self._cache.get(key)
            return record.get("versions", {}) if record else {}

        versions = payload or {}
        self._cache[key] = {"versions": versions, "fetched_at": dt_util.utcnow().isoformat()}
        # Delayed/coalesced, not an immediate async_save -- same reasoning as
        # community_verdict.py's own _async_remember: a lost write only costs
        # one extra HTTP re-fetch next time, never a wrong user-visible
        # decision.
        self._store.async_delay_save(lambda: self._cache, 1.0)
        return versions
