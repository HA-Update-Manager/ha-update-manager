"""Reads (never writes) a community-computed verdict for an update entity,
from the community-votes repo built and live-tested 2026-07-22 (see
FUTURE.md): https://github.com/HA-Update-Manager/community-votes. Read-only
slice only, no voting, no OAuth, no settings toggle (confirmed with the
user: pure reading, nothing sent, always on).

Identity resolution itself (which category, which path) lives in
hacs_identity.py's own resolve_identity (pure, unit-tested, no homeassistant
import) plus device_identity.py's resolve_full_identity on top of it (the
two categories -- devices, apps -- that need a real hass to look up a
device_registry entry), not here.

Cache is time-based, not purely version-based like coordinator.py's own
_async_get_available_since: found live 2026-07-22, testing against a real
vote, that a "not yet rated" result cached forever per version would never
notice new votes cast later for a version that's still pending (unlike
available_since, where the answer genuinely can't change once known, a vote
count can keep climbing while a device is still sitting on the same pending
version).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .device_identity import resolve_full_identity
from .hacs_identity import ResolvedIdentity

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_community_verdict"

VOTES_REPO_RAW_BASE = "https://raw.githubusercontent.com/HA-Update-Manager/community-votes/main"

# Applies to every outcome (found, not-yet-rated, or unidentifiable) so a
# fresh vote or an updated count is noticed within an hour without refetching
# on every single ~15-minute coordinator refresh tick either.
_REFRESH_INTERVAL = timedelta(hours=1)


async def _fetch_json(hass: HomeAssistant, url: str) -> dict[str, Any] | None:
    """Raw fetch, no caching: shared by every read below (found by review:
    _verdict.json's own fetch and the later per-voter one had copied the
    same 404/raise_for_status/json(content_type=None) block). None only
    for a confirmed 404 -- everything else (timeout, 5xx, DNS hiccup) is
    re-raised, since callers handle a transient failure differently (one
    falls back to a stale cached value, others just treat it as a miss)."""
    session = async_get_clientsession(hass)
    async with session.get(url, timeout=10) as response:
        if response.status == 404:
            return None
        response.raise_for_status()
        return await response.json(content_type=None)


async def _fetch_verdict_json(hass: HomeAssistant, votes_path: str) -> dict[str, Any] | None:
    return await _fetch_json(hass, f"{VOTES_REPO_RAW_BASE}/votes/{votes_path}/_verdict.json")


async def async_fetch_my_vote(hass: HomeAssistant, identity: ResolvedIdentity, username: str) -> str | None:
    """The verdict from *your own* vote file for this identity, straight
    from community-votes itself (`votes/<votes_path>/<username>.json`,
    verified against process-vote.yml's own votePath: every vote is its
    own file, literally named after the GitHub username that cast it), not
    just the aggregate counts. Direct user feedback, 2026-07-23 ("maar je
    weet toch dat ik klaptafel ben?"): my_votes.py's own local record only
    ever covers a vote cast after that module existed -- this covers every
    vote that's actually been processed already, regardless of when, at
    the cost of one extra request. None on a 404 (never voted, or not
    processed yet) or any transient failure alike -- this is a nice-to-
    have enrichment of the verdict line, not something worth surfacing an
    error for."""
    try:
        payload = await _fetch_json(hass, f"{VOTES_REPO_RAW_BASE}/votes/{identity.votes_path}/{username}.json")
    except Exception:
        _LOGGER.debug("Couldn't fetch %s's own vote for %s", username, identity.votes_path, exc_info=True)
        return None
    return payload.get("verdict") if payload else None


class CommunityVerdictManager:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store: Store[dict[str, dict[str, Any]]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        # entity_id -> {"version", "verdict", "trusted_vote",
        # "trusted_voters_matched", "fetched_at"}. Re-fetched whenever
        # latest_version changes (same as available_since) OR the cached
        # record is simply older than _REFRESH_INTERVAL, whichever comes
        # first.
        self._cache: dict[str, dict[str, Any]] = {}
        # Empty by default (see const.py's own CONF_TRUSTED_VOTERS): a list,
        # not a single username, so more than one person's judgement can be
        # trusted at once (direct user feedback, 2026-07-23).
        self._trusted_voters: list[str] = []

    async def async_load(self) -> None:
        self._cache = await self._store.async_load() or {}

    def set_trusted_voters(self, usernames: list[str]) -> None:
        self._trusted_voters = usernames

    def peek_cached_verdict(self, entity_id: str) -> dict[str, Any] | None:
        """Synchronous, no fetch: whatever verdict was last known for this
        entity, stale or not, or None if it's never been looked up at all.
        Found by review, 2026-07-22: coordinator.py's own bulk scan used to
        await async_get_verdict inline, serializing a real HTTP round-trip
        (on a cache miss/expiry) into every single entity's staging-status
        write, even though the verdict is purely cosmetic and never gates
        that decision. Coordinator now uses this for an entity's cache
        entry immediately, and refreshes it in the background separately
        (see coordinator.py's own _async_refresh_community_verdict)."""
        record = self._cache.get(entity_id)
        return record.get("verdict") if record else None

    def peek_cached_trusted_vote(self, entity_id: str, latest_version: str) -> tuple[str | None, list[str]]:
        """Same reasoning/shape as peek_cached_verdict, for the trusted-
        voters' own already-aggregated verdict instead: (verdict, which
        usernames' votes produced it). (None, []) if never looked up, no
        trusted voter is configured at all, or the cached record is for a
        different version than latest_version.

        Found by review, 2026-07-23: this used to skip the version check
        peek_cached_verdict/_fresh_cached_verdict both already do, so a
        version bump (latest_version changes, but the cache entry hasn't
        been re-fetched yet -- this synchronous peek runs before that
        background refetch resolves) could apply an older version's
        trusted-healthy verdict to the new, not-actually-voted-on version,
        auto-installing it on the strength of a vote that was never cast
        for it."""
        record = self._cache.get(entity_id)
        if not record or record.get("version") != latest_version:
            return None, []
        return record.get("trusted_vote"), record.get("trusted_voters_matched", [])

    def _fresh_cached_verdict(self, entity_id: str, latest_version: str) -> tuple[bool, Any]:
        record = self._cache.get(entity_id)
        if record is None or record.get("version") != latest_version:
            return False, None
        fetched_at = dt_util.parse_datetime(record.get("fetched_at", ""))
        if fetched_at is None or dt_util.utcnow() - fetched_at >= _REFRESH_INTERVAL:
            return False, None
        return True, record.get("verdict")

    async def _async_remember(
        self,
        entity_id: str,
        latest_version: str,
        verdict: dict[str, Any] | None,
        trusted_vote: str | None = None,
        trusted_voters_matched: list[str] | None = None,
    ) -> None:
        self._cache[entity_id] = {
            "version": latest_version,
            "verdict": verdict,
            "trusted_vote": trusted_vote,
            "trusted_voters_matched": trusted_voters_matched or [],
            "fetched_at": dt_util.utcnow().isoformat(),
        }
        # Delayed/coalesced, not an immediate async_save: found by review,
        # this used to write the entire cache dict to disk on every single
        # call, including the common non-HACS-identified case, one full
        # write per entity instead of one for a whole burst. Unlike
        # coordinator.py's own available_since store, there's no crash-
        # safety story here to preserve: a lost write only costs one extra
        # HTTP re-fetch next time, never a wrong user-visible decision, so
        # this is safe to debounce.
        self._store.async_delay_save(lambda: self._cache, 1.0)

    async def _async_fetch_trusted_vote(self, identity: ResolvedIdentity) -> tuple[str | None, list[str]]:
        """Every configured trusted username's own vote for this identity,
        fetched concurrently, then aggregated the same asymmetric-safety
        way this project already resolves the *aggregate* auto-install
        quorum (FUTURE.md's own point 5): any "problematic" among them
        wins outright, even if others among them voted "healthy" -- only
        if none of them did, and at least one voted "healthy", does that
        apply instead. Short-circuits to (None, []) with no request at all
        when no trusted voter is configured."""
        # Snapshotted once, up front: found by review, re-reading
        # self._trusted_voters again after the gather below (to zip it with
        # the results) raced against a settings save reassigning it
        # mid-fetch (set_trusted_voters swaps in a whole new list, it
        # doesn't mutate in place), silently pairing one username's fetched
        # vote with a different username's name.
        trusted_voters = self._trusted_voters
        if not trusted_voters:
            return None, []
        results = await asyncio.gather(
            *(async_fetch_my_vote(self.hass, identity, username) for username in trusted_voters)
        )
        voted = dict(zip(trusted_voters, results))
        problematic = [username for username, verdict in voted.items() if verdict == "problematic"]
        if problematic:
            return "problematic", problematic
        healthy = [username for username, verdict in voted.items() if verdict == "healthy"]
        if healthy:
            return "healthy", healthy
        return None, []

    async def async_get_verdict(
        self, entity_id: str, release_url: str | None, latest_version: str
    ) -> dict[str, Any] | None:
        is_fresh, cached_verdict = self._fresh_cached_verdict(entity_id, latest_version)
        if is_fresh:
            return cached_verdict

        identity = resolve_full_identity(self.hass, entity_id, release_url, latest_version)
        if identity is None:
            await self._async_remember(entity_id, latest_version, None)
            return None

        try:
            verdict = await _fetch_verdict_json(self.hass, identity.votes_path)
        except Exception:
            # Transient (timeout, 5xx, DNS hiccup): logged, not surfaced as a
            # visible error. Falls back to whatever was last known for this
            # entity (even a stale record, so a badge doesn't flash on and
            # off just because one fetch hiccupped) instead of blanking it.
            _LOGGER.debug("Couldn't fetch community verdict for %s", entity_id, exc_info=True)
            record = self._cache.get(entity_id)
            return record.get("verdict") if record else None

        trusted_vote, trusted_voters_matched = await self._async_fetch_trusted_vote(identity)
        await self._async_remember(entity_id, latest_version, verdict, trusted_vote, trusted_voters_matched)
        return verdict


async def async_fetch_verdict_uncached(hass: HomeAssistant, identity: ResolvedIdentity) -> dict[str, Any] | None:
    """A direct, uncached lookup for an arbitrary already-resolved identity,
    not necessarily the entity's own current pending version, e.g. reading/
    voting from a specific History entry. Deliberately NOT
    CommunityVerdictManager's own cache (keyed only by entity_id, one
    record per entity, meant for the Updates-tab badge): reusing that here
    would let a historical lookup silently overwrite that entity's own
    "current pending version" cache entry, corrupting the badge. No caching
    here at all, this is a rare, user-initiated, one-off lookup (opening a
    History dialog), not a hot path worth optimizing. Takes the identity
    directly rather than (entity_id, release_url, version): callers already
    had to resolve it once to decide whether to call this at all (see
    websocket_api.py's own _resolve_identity_for_version), no reason to
    resolve it a second time here."""
    try:
        return await _fetch_verdict_json(hass, identity.votes_path)
    except Exception:
        _LOGGER.debug("Couldn't fetch community verdict for %s", identity.votes_path, exc_info=True)
        return None
