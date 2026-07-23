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
        # votes_path -> verdict. Keyed by the same votes_path community-votes
        # itself uses (see hacs_identity.py's ResolvedIdentity.votes_path),
        # not entity_id/version separately: a vote is tied to one specific
        # identity/version pair, exactly what votes_path already encodes.
        self._votes: dict[str, str] = {}

    async def async_load(self) -> None:
        self._votes = await self._store.async_load() or {}

    def my_verdict(self, votes_path: str) -> Verdict | None:
        return self._votes.get(votes_path)  # type: ignore[return-value]

    async def async_remember(self, votes_path: str, verdict: Verdict) -> None:
        self._votes[votes_path] = verdict
        await self._store.async_save(self._votes)
