"""Shared, thin HTTP helpers for community-votes' own two surfaces: its
plain public JSON files (read directly via raw.githubusercontent.com, no
auth, no API rate limit) and its GitHub Issues endpoint (write, via a
linked account's own access token). Reused by community_verdict.py/
community_vote.py (votes) and firmware_version_registry.py/
firmware_version_submit.py (the firmware-version mapping), which each used
to carry their own identical copy of one or the other (found by
/simplify)."""
from __future__ import annotations

import base64
import json
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_ISSUES_URL = "https://api.github.com/repos/HA-Update-Manager/community-votes/issues"
_CONTENTS_URL = "https://api.github.com/repos/HA-Update-Manager/community-votes/contents"


async def async_fetch_public_json(hass: HomeAssistant, url: str) -> dict[str, Any] | None:
    """None only for a confirmed 404 -- everything else (timeout, 5xx, DNS
    hiccup) is re-raised, since callers handle a transient failure
    differently (one falls back to a stale cached value, others just treat
    it as a miss)."""
    session = async_get_clientsession(hass)
    async with session.get(url, timeout=10) as response:
        if response.status == 404:
            return None
        response.raise_for_status()
        return await response.json(content_type=None)


async def async_fetch_authoritative_json(hass: HomeAssistant, access_token: str, path: str) -> dict[str, Any] | None:
    """Same shape as async_fetch_public_json (None only for a confirmed
    404), but via GitHub's own Contents API (authenticated) instead of
    raw.githubusercontent.com. That public endpoint is served through a
    CDN confirmed to lag the real repository content by minutes after a
    write (a well-documented GitHub behavior, not specific to this repo)
    -- normally an acceptable staleness window for display, but found
    live, 2026-11-24, to matter right before deciding whether to submit
    something: a submission check re-fetching that same cached endpoint
    moments after writing it can still see the pre-write state, concluding
    a pairing is new when the repository itself already has it, and
    resubmitting it. This endpoint talks to GitHub's own backend directly
    -- the same one process-firmware-version.yml's own readJson already
    uses internally, never a cache -- so a caller that has just submitted,
    or is about to, gets the real, current answer."""
    session = async_get_clientsession(hass)
    async with session.get(
        f"{_CONTENTS_URL}/{path}",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"},
        timeout=10,
    ) as response:
        if response.status == 404:
            return None
        response.raise_for_status()
        payload = await response.json(content_type=None)
    return json.loads(base64.b64decode(payload["content"]).decode("utf-8"))


async def async_post_community_votes_issue(hass: HomeAssistant, access_token: str, title: str, body: str) -> None:
    """Raises on failure (a non-2xx response, a network error) -- each
    caller decides how to treat that for its own feature (a user-visible
    error for a vote, a silent debug log for an automatic firmware-version
    submission, see each one's own module)."""
    session = async_get_clientsession(hass)
    async with session.post(
        _ISSUES_URL,
        json={"title": title, "body": body},
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"},
        timeout=10,
    ) as response:
        response.raise_for_status()
