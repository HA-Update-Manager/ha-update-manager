"""Reads (never writes) a community-computed verdict for a HACS-identified
update, from the community-votes repo built and live-tested 2026-07-22 (see
FUTURE.md): https://github.com/HA-Update-Manager/community-votes. Read-only
slice only, no voting, no OAuth, no settings toggle (confirmed with the
user: pure reading, nothing sent, always on).

Identity comes from the update entity's own `release_url` attribute, not
HACS-specific data, so any entity that happens to set a GitHub release URL
can get a verdict, not only HACS-installed ones. That attribute is treated as
an opaque string set by whatever integration backs the entity though, it is
*expected* to look like a GitHub release URL for most real integrations, but
nothing enforces that, so extraction is a tolerant regex with a silent
"no verdict available" fallback on a non-match, never a crash or a visible
error for entities that don't fit that shape.

Cache is time-based, not purely version-based like coordinator.py's own
_async_get_available_since: found live 2026-07-22, testing against a real
vote, that a "not yet rated" result cached forever per version would never
notice new votes cast later for a version that's still pending (unlike
available_since, where the answer genuinely can't change once known, a vote
count can keep climbing while a device is still sitting on the same pending
version).
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .hacs_identity import extract_hacs_identity

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_community_verdict"

VOTES_REPO_RAW_BASE = "https://raw.githubusercontent.com/HA-Update-Manager/community-votes/main"

# Applies to every outcome (found, not-yet-rated, or unidentifiable) so a
# fresh vote or an updated count is noticed within an hour without refetching
# on every single ~15-minute coordinator refresh tick either.
_REFRESH_INTERVAL = timedelta(hours=1)


class CommunityVerdictManager:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store: Store[dict[str, dict[str, Any]]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        # entity_id -> {"version", "verdict", "fetched_at"}. Re-fetched
        # whenever latest_version changes (same as available_since) OR the
        # cached record is simply older than _REFRESH_INTERVAL, whichever
        # comes first.
        self._cache: dict[str, dict[str, Any]] = {}

    async def async_load(self) -> None:
        self._cache = await self._store.async_load() or {}

    def _fresh_cached_verdict(self, entity_id: str, latest_version: str) -> tuple[bool, Any]:
        record = self._cache.get(entity_id)
        if record is None or record.get("version") != latest_version:
            return False, None
        fetched_at = dt_util.parse_datetime(record.get("fetched_at", ""))
        if fetched_at is None or dt_util.utcnow() - fetched_at >= _REFRESH_INTERVAL:
            return False, None
        return True, record.get("verdict")

    async def _async_remember(self, entity_id: str, latest_version: str, verdict: dict[str, Any] | None) -> None:
        self._cache[entity_id] = {
            "version": latest_version,
            "verdict": verdict,
            "fetched_at": dt_util.utcnow().isoformat(),
        }
        await self._store.async_save(self._cache)

    async def async_get_verdict(
        self, entity_id: str, release_url: str | None, latest_version: str
    ) -> dict[str, Any] | None:
        is_fresh, cached_verdict = self._fresh_cached_verdict(entity_id, latest_version)
        if is_fresh:
            return cached_verdict

        identity = extract_hacs_identity(release_url)
        if identity is None:
            await self._async_remember(entity_id, latest_version, None)
            return None

        owner, repo, version = identity
        url = f"{VOTES_REPO_RAW_BASE}/votes/hacs/{owner}/{repo}/{version}/_verdict.json"
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(url, timeout=10) as response:
                if response.status == 404:
                    await self._async_remember(entity_id, latest_version, None)
                    return None
                response.raise_for_status()
                verdict = await response.json(content_type=None)
        except Exception:
            # Transient (timeout, 5xx, DNS hiccup): logged, not surfaced as a
            # visible error. Falls back to whatever was last known for this
            # entity (even a stale record, so a badge doesn't flash on and
            # off just because one fetch hiccupped) instead of blanking it.
            _LOGGER.debug("Couldn't fetch community verdict for %s from %s", entity_id, url, exc_info=True)
            record = self._cache.get(entity_id)
            return record.get("verdict") if record else None

        await self._async_remember(entity_id, latest_version, verdict)
        return verdict
