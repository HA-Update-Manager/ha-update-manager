"""Tracks which community-votes path this HA instance has itself already
voted on, and what verdict, purely locally. community-votes' own aggregate
_verdict.json is never broken down by voter, and processing a freshly
submitted vote into that aggregate can lag behind the moment it's actually
submitted (found live, 2026-07-22: a vote just cast still read as "not yet
rated" seconds later). Read by websocket_api.py's own verdict_for_version
handler to let the panel say "you and N others", not just a bare count,
written by that same module's vote handler right after a submission
actually succeeds.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Literal

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .vote_freshness import is_vote_stale

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_my_votes"

Verdict = Literal["healthy", "problematic"]


class MyVotesManager:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store: Store[dict[str, dict[str, Any]]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        # jump_key -> {"verdict": ..., "voted_at": <ISO timestamp>}. Keyed by
        # ResolvedIdentity.jump_key (a vote is tied to one specific
        # identity+jump pair, not entity_id/version separately -- jump_key
        # already encodes exactly that). Changed 2026-07-24 from the old,
        # single-version votes_path: an old stored key simply won't match a
        # freshly resolved jump_key, a one-time cache miss that falls back to
        # a remote fetch and backfills, same graceful degradation this module
        # already relies on for a vote cast before it existed at all.
        #
        # voted_at added 2026-08-01 (direct user feedback: deleting a vote
        # file directly on community-votes still showed "you voted" in the
        # panel, with no way to vote again) so websocket_api.py's own
        # verdict_for_version handler can tell a vote it just cast seconds
        # ago (community-votes' own Action hasn't processed it into the live
        # payload yet, see this module's own docstring above) apart from one
        # that's been sitting here for a while and has since genuinely
        # vanished from community-votes (deleted externally) -- only the
        # latter should ever be reconciled away, the former must keep being
        # trusted immediately or that exact "not yet rated" bug comes back.
        self._votes: dict[str, dict[str, Any]] = {}

    async def async_load(self) -> None:
        # Migrates any pre-2026-08-01 entry (jump_key -> plain verdict
        # string) to the current shape (jump_key -> {"verdict", "voted_at"})
        # right away, once, rather than treating every single read site as
        # having to handle both shapes forever after -- found live
        # (2026-08-01, direct user feedback: the community section
        # disappeared entirely on a History item): my_verdict/is_stale doing
        # entry["verdict"]/entry.get("voted_at") straight on a leftover
        # plain-string entry raised (TypeError/AttributeError), and that
        # exception propagating out of a websocket_api.py handler is exactly
        # what made the whole section vanish instead of just that one row
        # degrading gracefully. voted_at is unknown for a migrated entry, so
        # is_stale treats it the same as "no voted_at at all" -- always
        # stale, safe to reconcile against live data on the very next check.
        raw = await self._store.async_load() or {}
        self._votes = {
            jump_key: entry if isinstance(entry, dict) else {"verdict": entry, "voted_at": None}
            for jump_key, entry in raw.items()
        }

    def my_verdict(self, jump_key: str) -> Verdict | None:
        entry = self._votes.get(jump_key)
        return entry["verdict"] if entry else None

    def jump_keys(self) -> list[str]:
        """A snapshot copy, not a live view -- websocket_api.py's own
        refresh-triggered reconciliation iterates this while calling
        async_forget on some of them, which mutates self._votes; iterating a
        live dict_keys view while it's being mutated would raise."""
        return list(self._votes.keys())

    def is_stale(self, jump_key: str, grace_period: timedelta) -> bool:
        """True if this jump_key has a remembered vote old enough that it's
        safe to cross-check against live community-votes data and forget it
        if it's genuinely gone (see vote_freshness.is_vote_stale's own
        docstring for the full reasoning, including the no-voted_at-at-all
        case, which a migrated pre-2026-08-01 entry -- see async_load's own
        comment -- also falls under). False for a jump_key with no
        remembered vote at all -- nothing to reconcile."""
        entry = self._votes.get(jump_key)
        if entry is None:
            return False
        return is_vote_stale(entry.get("voted_at"), dt_util.utcnow(), grace_period)

    async def async_remember(self, jump_key: str, verdict: Verdict) -> None:
        self._votes[jump_key] = {"verdict": verdict, "voted_at": dt_util.utcnow().isoformat()}
        await self._store.async_save(self._votes)

    async def async_forget(self, jump_key: str) -> None:
        """Removes a remembered vote that live community-votes data no
        longer confirms (see is_stale's own comment) -- the panel then falls
        back to treating this jump as never-voted-on, offering the vote
        controls again instead of a permanently stuck "you voted" state."""
        if jump_key in self._votes:
            del self._votes[jump_key]
            await self._store.async_save(self._votes)

    async def async_forget_many(self, jump_keys: list[str]) -> None:
        """Same as calling async_forget once per jump_key, but a single
        Store.async_save() (one JSON file write) for the whole batch instead
        of one per key -- found by review, 2026-08-01: websocket_api.py's own
        _async_reconcile_my_votes (the manual refresh button's "tell me the
        truth now" reconciliation) used to await async_forget in a plain
        for-loop, turning N genuinely-gone votes into N sequential file
        writes for no reason, since nothing reads self._votes in between
        them. A no-op (no save at all) when none of the given keys are
        actually still present."""
        removed_any = False
        for jump_key in jump_keys:
            if jump_key in self._votes:
                del self._votes[jump_key]
                removed_any = True
        if removed_any:
            await self._store.async_save(self._votes)
