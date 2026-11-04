"""Proactively learns a release's own minimum Home Assistant Core
requirement straight from its repository's hacs.json, via GitHub's own
public Contents API, so install_manager.py can mark an entity postponed
*before* ever attempting an install, not only after a failed one (see
semver.py's own min_ha_version_required for that reactive counterpart,
still relied on for whatever this can't reach, e.g. a release whose
release_url doesn't parse as a GitHub one at all).

Deliberately not read from HACS's/Marketplace's own in-memory repository
registry instead, even though both already hold this exact value in memory
(repository_manifest.homeassistant, confirmed against both's real source,
2026-11-04): neither exposes it through anything public, so that path would
mean reaching into another integration's own undocumented internals, able
to break silently on either one's next unrelated refactor. GitHub's own
Contents API is the same stable, documented surface this project already
depends on elsewhere (see websocket_api.py's own async_fetch_github_release_
notes), just one more endpoint on it.

Same (owner, repo, tag) a release_url's own tag will never resolve to a
different hacs.json body once published (GitHub tags are immutable in
practice), so a successful lookup is cached forever, never re-fetched for
the same tag again."""
from __future__ import annotations

import base64
import binascii
import json
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)


async def async_fetch_min_ha_version(
    hass: HomeAssistant, owner: str, repo: str, tag: str, access_token: str | None
) -> tuple[bool, str | None]:
    """(confirmed, version). version is the plain "homeassistant" string
    hacs.json declares at this exact tag, None whenever there's genuinely
    nothing to find there (no hacs.json at all, e.g. a repo that doesn't use
    HACS/Marketplace, or the manifest doesn't set this key). confirmed is
    False on a transient failure (network/timeout/rate limit/malformed
    response), deliberately distinct from a real "nothing to find", so the
    caller (install_manager.py's own cache, this module's top comment) only
    ever caches a *confirmed* answer, trying again on the next tick for
    anything that failed for reasons that have nothing to do with this exact
    tag's own content, which can never actually change once published.

    Uses the linked GitHub account's own token when available (5000
    requests/hour), same as async_fetch_github_release_notes: an
    unauthenticated request still works for a public repo (60/hour), this
    just makes that budget shared with every other GitHub lookup this
    integration already does."""
    headers = {"Accept": "application/vnd.github+json"}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    session = async_get_clientsession(hass)
    try:
        async with session.get(
            f"https://api.github.com/repos/{owner}/{repo}/contents/hacs.json",
            headers=headers,
            params={"ref": tag},
            timeout=10,
        ) as response:
            if response.status == 404:
                # A real, stable fact about this exact tag (no hacs.json
                # there at all): confirmed, safe to cache.
                return (True, None)
            if response.status != 200:
                return (False, None)
            payload: dict[str, Any] = await response.json()
    except Exception:
        _LOGGER.debug("Update Manager couldn't fetch hacs.json for %s/%s@%s", owner, repo, tag)
        return (False, None)

    try:
        manifest = json.loads(base64.b64decode(payload["content"]))
    except (KeyError, ValueError, TypeError, binascii.Error, json.JSONDecodeError):
        # The response itself came back fine (a real 200), just not content
        # this module can parse as hacs.json, confirmed either way, no
        # reason to keep re-fetching the exact same malformed body.
        return (True, None)

    version = manifest.get("homeassistant")
    return (True, version if isinstance(version, str) else None)
