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

from typing import Literal

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_my_votes"

Verdict = Literal["healthy", "problematic"]


class MyVotesManager:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store: Store[dict[str, str]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        # jump_key -> verdict. Keyed by ResolvedIdentity.jump_key (a vote is
        # tied to one specific identity+jump pair, not entity_id/version
        # separately -- jump_key already encodes exactly that). Changed
        # 2026-07-24 from the old, single-version votes_path: an old stored
        # key simply won't match a freshly resolved jump_key, a one-time
        # cache miss that falls back to a remote fetch and backfills, same
        # graceful degradation this module already relies on for a vote
        # cast before it existed at all.
        self._votes: dict[str, str] = {}

    async def async_load(self) -> None:
        self._votes = await self._store.async_load() or {}

    def my_verdict(self, jump_key: str) -> Verdict | None:
        return self._votes.get(jump_key)  # type: ignore[return-value]

    async def async_remember(self, jump_key: str, verdict: Verdict) -> None:
        self._votes[jump_key] = verdict
        await self._store.async_save(self._votes)
