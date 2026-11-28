"""Reads this user's own voting stats from community-votes' daily-
regenerated, public analysis/voters.json (see that file's own README in
the community-votes repo for the full shape): total/healthy/problematic
vote counts and a reliability score, computed across every jump in the
repo, not just this household's own.

Same shared low-level fetch as community_verdict.py/
firmware_version_registry.py (community_votes_api.py's own
async_fetch_public_json: a single, no-auth, no-API-rate-limit static file
read, direct user feedback, 2026-11-27, after first considering and
rejecting GitHub's own Search API for this exact purpose over its far
stricter rate limit, this file needing no live computation at all).
Deliberately much simpler than firmware_version_registry.py's own
per-model cache: one file, read whole, this user's own entry picked out of
it client-side (server side, in this module), nothing cached per key."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .community_votes_api import async_fetch_public_json
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_voter_stats"

VOTER_STATS_URL = "https://raw.githubusercontent.com/HA-Update-Manager/community-votes/main/analysis/voters.json"

# This file is itself only regenerated once a day by its own workflow, so
# even an hour (same cadence as community_verdict.py/
# firmware_version_registry.py's own _REFRESH_INTERVAL, for consistency)
# is generous, not the bottleneck.
_REFRESH_INTERVAL = timedelta(hours=1)


def _find_voter(username: str, voters: list[dict[str, Any]]) -> dict[str, Any] | None:
    normalized = username.lstrip("@").lower()
    for voter in voters:
        if str(voter.get("username", "")).lower() == normalized:
            return voter
    return None


class VoterStatsManager:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        # The raw "voters" list straight from voters.json, plus when it was
        # last fetched. Not keyed per-username, the whole file is small
        # and only ever fetched whole anyway.
        self._cache: dict[str, Any] = {}

    async def async_load(self) -> None:
        self._cache = await self._store.async_load() or {}

    def peek_cached_stats(self, username: str) -> dict[str, Any] | None:
        """No network, safe for a hot path. Same reasoning as
        firmware_version_registry.py's own peek_cached_versions."""
        return _find_voter(username, self._cache.get("voters", []))

    def _fresh_cached(self) -> bool:
        fetched_at = dt_util.parse_datetime(self._cache.get("fetched_at", ""))
        return fetched_at is not None and dt_util.utcnow() - fetched_at < _REFRESH_INTERVAL

    async def async_get_stats(self, username: str, *, force: bool = False) -> dict[str, Any] | None:
        if not force and self._fresh_cached():
            return _find_voter(username, self._cache.get("voters", []))

        try:
            payload = await async_fetch_public_json(self.hass, VOTER_STATS_URL)
        except Exception:
            # Transient (timeout, 5xx, DNS hiccup): falls back to whatever
            # was last known instead of blanking it, same graceful-
            # degradation reasoning as community_verdict.py's own
            # async_get_verdict.
            _LOGGER.debug("Couldn't fetch voter stats", exc_info=True)
            return _find_voter(username, self._cache.get("voters", []))

        voters = (payload or {}).get("voters", [])
        self._cache = {"voters": voters, "fetched_at": dt_util.utcnow().isoformat()}
        # Delayed/coalesced, not an immediate async_save. Same reasoning
        # as community_verdict.py's own _async_remember: a lost write only
        # costs one extra HTTP re-fetch next time, never a wrong user-
        # visible decision.
        self._store.async_delay_save(lambda: self._cache, 1.0)
        return _find_voter(username, voters)
