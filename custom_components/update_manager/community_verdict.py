"""Reads (never writes) a community-computed verdict for an update entity,
from the community-votes repo, built and live-tested 2026-07-22:
https://github.com/HA-Update-Manager/community-votes. Read-only
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

A vote/verdict is identified by the exact version jump (from_version ->
to_version), not the destination version alone (changed 2026-07-24, see
hacs_identity.py's own docstring for why). community-votes stores every jump
landing on the same to_version in one shared file
(votes/<category>/.../<to_version>.json, shape: {"jumps": {"<from_version>":
{"votes": {...}, "verdict": {...}}, ...}}) -- one fetch of that file answers
"what's my own jump's verdict", "what did a specific username vote", and
"what do other jumps to this same destination look like" all at once, so
every read in this module funnels through one shared low-level fetch,
_fetch_to_version_json, followed by pure, synchronous extraction over the
resulting payload.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

# async_fetch_verdict_uncached's own empty return: (verdict, other_jumps,
# trusted_vote, trusted_voters_matched, problematic_reasons, my_reason,
# my_live_verdict, fetch_ok), all "nothing to report" -- shared with
# websocket_api.py's own identity-is-None fallback so the two tuples can't
# drift apart as this shape grows further (it already grew once, 5 elements
# to 6, when my_reason was added; 6 to 8, when my_live_verdict/fetch_ok were
# added for the my_votes.py reconciliation check below).
#
# fetch_ok is deliberately False here, not True: this exact tuple is also
# returned on a genuine fetch failure (see async_fetch_verdict_uncached's own
# except branch below), where my_live_verdict being None must NOT be read as
# "confirmed no vote on community-votes" -- that would wrongly let
# websocket_api.py forget a real remembered vote just because of a transient
# network hiccup. A real, successful-but-empty fetch (e.g. a genuine 404,
# nothing rated yet) builds its own tuple below with fetch_ok=True instead,
# never reuses this constant.
EMPTY_VERDICT_RESULT: tuple[Any, ...] = (None, [], None, [], [], None, None, False)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .community_verdict_payload import (
    my_problematic_reason_from_payload,
    my_vote_from_payload,
    other_jumps_from_payload,
    problematic_reasons_from_payload,
    trusted_vote_from_payload,
    verdict_from_payload,
)
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


async def _fetch_to_version_json(hass: HomeAssistant, to_version_path: str) -> dict[str, Any] | None:
    """The whole destination-version payload -- every jump (from_version)
    that's been rated for it, and every voter's own entry within each jump.
    Every other function in this module that needs anything jump-related
    (my own jump's verdict, a specific username's vote, other jumps to the
    same destination) fetches this once and extracts from it via
    community_verdict_payload.py's own pure helpers, rather than each doing
    its own separate request."""
    return await _fetch_json(hass, f"{VOTES_REPO_RAW_BASE}/votes/{to_version_path}.json")


async def async_fetch_vote_for_jump_key(
    hass: HomeAssistant, to_version_path: str, from_version: str, username: str
) -> str | None:
    """my_vote_from_payload, but keyed directly by a jump's own
    to_version_path/from_version rather than a full ResolvedIdentity -- used
    by websocket_api.py's own refresh_community_verdicts handler when
    reconciling my_votes.py's *entire* local record (direct user feedback,
    2026-08-01, asking for this to also happen from the refresh button),
    where only the jump_key string is available for a possibly-old/no-longer-pending
    jump (see ResolvedIdentity.jump_key: it already encodes
    to_version_path::from_version, so splitting that back apart is enough,
    no need to re-resolve a full identity for an entity that might not even
    still exist). Raises on a genuine fetch failure, same as
    _fetch_to_version_json itself -- unlike async_fetch_my_vote below, which
    is a best-effort single-jump enrichment where swallowing a failure is
    fine, a caller reconciling many remembered votes at once must be able to
    tell "couldn't check" apart from "confirmed no vote", or a transient
    network hiccup would wrongly forget a still-real vote."""
    payload = await _fetch_to_version_json(hass, to_version_path)
    return my_vote_from_payload(payload, from_version, username)


async def async_fetch_my_vote(hass: HomeAssistant, identity: ResolvedIdentity, username: str) -> str | None:
    """The verdict from *your own* vote for this exact identity+jump,
    straight from community-votes itself, not just the aggregate counts.
    Direct user feedback, 2026-07-23 ("maar je weet toch dat ik klaptafel
    ben?"): my_votes.py's own local record only ever covers a vote cast
    after that module existed -- this covers every vote that's actually been
    processed already, regardless of when, at the cost of one extra request.
    None on a 404 (never voted, or not processed yet) or any transient
    failure alike -- this is a nice-to-have enrichment of the verdict line,
    not something worth surfacing an error for."""
    try:
        return await async_fetch_vote_for_jump_key(hass, identity.to_version_path, identity.from_version, username)
    except Exception:
        _LOGGER.debug("Couldn't fetch %s's own vote for %s", username, identity.to_version_path, exc_info=True)
        return None


class CommunityVerdictManager:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store: Store[dict[str, dict[str, Any]]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        # entity_id -> {"to_version", "from_version", "verdict",
        # "trusted_vote", "trusted_voters_matched", "fetched_at"}.
        # Re-fetched whenever latest_version OR installed_version changes
        # (same as available_since) OR the cached record is simply older
        # than _REFRESH_INTERVAL, whichever comes first.
        self._cache: dict[str, dict[str, Any]] = {}
        # Empty by default (see const.py's own CONF_TRUSTED_VOTERS): a list,
        # not a single username, so more than one person's judgement can be
        # trusted at once (direct user feedback, 2026-07-23).
        self._trusted_voters: list[str] = []

    async def async_load(self) -> None:
        self._cache = await self._store.async_load() or {}

    def set_trusted_voters(self, usernames: list[str]) -> None:
        self._trusted_voters = usernames

    @property
    def trusted_voters(self) -> list[str]:
        """The currently configured trusted-voter usernames, for callers
        outside this module doing their own one-off uncached lookup (see
        async_fetch_verdict_uncached) -- there's exactly one source of
        truth for this list (set via set_trusted_voters whenever settings
        are saved), no reason for websocket_api.py to keep its own copy."""
        return list(self._trusted_voters)

    def _cached_record(self, entity_id: str, to_version: str, from_version: str) -> dict[str, Any] | None:
        """The cached record for entity_id, or None if it's never been
        looked up at all, or it's for a different jump than requested --
        shared version-matching logic for peek_cached_verdict/
        peek_cached_trusted_vote/_fresh_cached, all of which must not reuse
        a stale unrelated jump's data (found by review, 2026-07-23, applied
        to peek_cached_trusted_vote first: a version bump, or an
        intermediate manual install changing from_version, can otherwise
        apply an old jump's verdict to a new one nobody's actually voted
        on)."""
        record = self._cache.get(entity_id)
        if not record or record.get("to_version") != to_version or record.get("from_version") != from_version:
            return None
        return record

    def peek_cached_verdict(self, entity_id: str, to_version: str, from_version: str) -> dict[str, Any] | None:
        """Synchronous, no fetch: whatever verdict was last known for this
        entity's exact jump, stale or not, or None if it's never been
        looked up (or is for a different jump). Found by review, 2026-07-22:
        coordinator.py's own bulk scan used to await async_get_verdict
        inline, serializing a real HTTP round-trip (on a cache miss/expiry)
        into every single entity's staging-status write, even though the
        verdict is purely cosmetic and never gates that decision.
        Coordinator now uses this for an entity's cache entry immediately,
        and refreshes it in the background separately (see coordinator.py's
        own _async_refresh_community_verdict)."""
        record = self._cached_record(entity_id, to_version, from_version)
        return record.get("verdict") if record else None

    def peek_cached_trusted_vote(
        self, entity_id: str, to_version: str, from_version: str
    ) -> tuple[str | None, list[str]]:
        """Same reasoning/shape as peek_cached_verdict, for the trusted-
        voters' own already-aggregated verdict instead: (verdict, which
        usernames' votes produced it). (None, []) if never looked up, no
        trusted voter is configured at all, or the cached record is for a
        different jump than requested."""
        record = self._cached_record(entity_id, to_version, from_version)
        if not record:
            return None, []
        return record.get("trusted_vote"), record.get("trusted_voters_matched", [])

    def _fresh_cached(self, entity_id: str, to_version: str, from_version: str) -> tuple[bool, Any]:
        record = self._cached_record(entity_id, to_version, from_version)
        if record is None:
            return False, None
        fetched_at = dt_util.parse_datetime(record.get("fetched_at", ""))
        if fetched_at is None or dt_util.utcnow() - fetched_at >= _REFRESH_INTERVAL:
            return False, None
        return True, record.get("verdict")

    async def _async_remember(
        self,
        entity_id: str,
        to_version: str,
        from_version: str,
        verdict: dict[str, Any] | None,
        trusted_vote: str | None = None,
        trusted_voters_matched: list[str] | None = None,
    ) -> None:
        self._cache[entity_id] = {
            "to_version": to_version,
            "from_version": from_version,
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

    async def async_get_verdict(
        self,
        entity_id: str,
        release_url: str | None,
        latest_version: str,
        installed_version: str | None,
        *,
        force: bool = False,
    ) -> dict[str, Any] | None:
        # No installed_version at all (entity hasn't reported it yet):
        # unidentifiable, same graceful degradation as a missing release_url
        # below -- there's no valid jump to resolve an identity for, and
        # nothing here is a network call worth caching against, unlike the
        # identity-resolution-failed case below.
        if installed_version is None:
            return None

        # force=True skips the freshness check entirely, always doing a
        # live fetch -- the panel's own manual refresh button, direct user
        # feedback 2026-07-25: clicking refresh should also pull in the
        # latest vote data, not silently keep showing whatever was cached
        # up to an hour ago.
        if not force:
            is_fresh, cached_verdict = self._fresh_cached(entity_id, latest_version, installed_version)
            if is_fresh:
                return cached_verdict

        identity = resolve_full_identity(self.hass, entity_id, release_url, latest_version, installed_version)
        if identity is None:
            await self._async_remember(entity_id, latest_version, installed_version, None)
            return None

        try:
            payload = await _fetch_to_version_json(self.hass, identity.to_version_path)
        except Exception:
            # Transient (timeout, 5xx, DNS hiccup): logged, not surfaced as a
            # visible error. Falls back to whatever was last known for this
            # entity (even a stale record, so a badge doesn't flash on and
            # off just because one fetch hiccupped) instead of blanking it.
            _LOGGER.debug("Couldn't fetch community verdict for %s", entity_id, exc_info=True)
            record = self._cached_record(entity_id, identity.to_version, identity.from_version)
            return record.get("verdict") if record else None

        # One fetch, both derived facts: the aggregate verdict for my own
        # jump, and the trusted-voter check (changed 2026-07-24 -- used to
        # be a second round of N separate requests, one per configured
        # trusted username, now a synchronous lookup over the same payload).
        verdict = verdict_from_payload(payload, identity.from_version)
        trusted_vote, trusted_voters_matched = trusted_vote_from_payload(
            payload, identity.from_version, self._trusted_voters
        )
        await self._async_remember(
            entity_id, identity.to_version, identity.from_version, verdict, trusted_vote, trusted_voters_matched
        )
        return verdict


async def async_fetch_verdict_uncached(
    hass: HomeAssistant,
    identity: ResolvedIdentity,
    trusted_voters: list[str] | None = None,
    username: str | None = None,
) -> tuple[
    dict[str, Any] | None,
    list[dict[str, Any]],
    str | None,
    list[str],
    list[dict[str, Any]],
    dict[str, Any] | None,
    str | None,
    bool,
]:
    """A direct, uncached lookup for an arbitrary already-resolved identity,
    not necessarily the entity's own current pending jump, e.g. reading/
    voting from a specific History entry. Deliberately NOT
    CommunityVerdictManager's own cache (keyed only by entity_id, one
    record per entity, meant for the Updates-tab badge): reusing that here
    would let a historical lookup silently overwrite that entity's own
    "current pending jump" cache entry, corrupting the badge. No caching
    here at all, this is a rare, user-initiated, one-off lookup (opening a
    dialog), not a hot path worth optimizing. Takes the identity directly
    rather than (entity_id, release_url, to_version, from_version): callers
    already had to resolve it once to decide whether to call this at all
    (see websocket_api.py's own _resolve_identity_for_version), no reason to
    resolve it a second time here.

    Returns (my own jump's verdict, other jumps to this same destination,
    trusted vote, trusted voters matched, *other* problematic voters' own
    reasons, my own problematic reason, my own live verdict, whether this
    fetch actually succeeded) -- all derived from the one fetch, direct user
    feedback 2026-07-24 (other_jumps), 2026-07-27 (trusted_vote/
    trusted_voters_matched: the dialog's own verdict line
    for a specific jump had no idea whether a trusted voter happened to be
    among the people who voted on it, even though that's exactly what changes
    auto-install behavior for this jump), 2026-07-29 (problematic_
    reasons/my_reason: a problematic vote's own reason was nowhere to be
    found in the interface), and
    2026-08-01 (my_live_verdict/fetch_ok, direct user feedback: deleting a
    vote file on community-votes still left the panel showing "you voted" --
    websocket_api.py's own verdict_for_version handler cross-checks
    my_votes.py's local record against this, since it's already fetching
    this exact payload anyway, no extra request needed).
    `username` (the caller's own linked GitHub username, if any) is
    resolved once here and used for excluding your own entry from the
    generic list, finding it directly for my_reason, and this same
    my_live_verdict check -- found by review, 2026-07-29: the previous
    version left the caller (websocket_api.py) to search the already-capped
    problematic_reasons list for its own username, which could silently
    miss it whenever enough other, more recent votes existed (see
    problematic_reasons_from_payload's own docstring). trusted_voters/
    username both default to none (not every caller cares, e.g. a caller
    that already knows this entity has no pending update at all)."""
    try:
        payload = await _fetch_to_version_json(hass, identity.to_version_path)
    except Exception:
        _LOGGER.debug("Couldn't fetch community verdict for %s", identity.to_version_path, exc_info=True)
        return EMPTY_VERDICT_RESULT
    trusted_vote, trusted_voters_matched = trusted_vote_from_payload(
        payload, identity.from_version, trusted_voters or []
    )
    return (
        verdict_from_payload(payload, identity.from_version),
        other_jumps_from_payload(payload, identity.from_version),
        trusted_vote,
        trusted_voters_matched,
        problematic_reasons_from_payload(payload, identity.from_version, exclude_username=username),
        my_problematic_reason_from_payload(payload, identity.from_version, username),
        my_vote_from_payload(payload, identity.from_version, username) if username else None,
        True,
    )
