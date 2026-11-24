"""Submits a newly-observed (manufacturer/model, raw OTA version) -> real
firmware version pairing to community-votes as a GitHub Issue, mirroring
community_vote.py's own shape for writing (same repo, same account-linking
story: any GitHub account can open an issue on a public repo the target App
is installed on, regardless of collaborator status, see github_auth.py).

The issue body itself is built by firmware_version_issue_body.py, kept
pure/HA-independent and unit-tested there rather than here, same reasoning
as community_vote.py's own split with vote_issue_body.py.

Unlike a vote, this fires automatically and often, with no human decision
moment behind it -- callers (coordinator.py's own background task) catch
whatever this raises and log it at debug level only, never surface a
user-visible error for it.
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .community_votes_api import async_post_community_votes_issue
from .firmware_version_issue_body import build_issue_body

_ISSUES_URL = "https://api.github.com/repos/HA-Update-Manager/community-votes/issues"


async def async_submit_firmware_version(
    hass: HomeAssistant,
    access_token: str,
    manufacturer: str,
    model: str,
    raw_version: int,
    real_version: str,
    integration_version: str,
) -> None:
    """Raises on failure (a non-2xx response, a network error) -- the caller
    decides how to treat that, see this module's own docstring."""
    body = build_issue_body(manufacturer, model, raw_version, real_version, integration_version)
    await async_post_community_votes_issue(hass, access_token, "[firmware-version]", body)


async def async_has_pending_submission(
    hass: HomeAssistant, access_token: str, manufacturer: str, model: str, raw_version: int
) -> bool:
    """True if an open, not-yet-processed [firmware-version] issue already
    exists for this exact (manufacturer, model, raw_version) -- checked
    live against GitHub itself right before ever submitting a new one.
    Replaces an earlier local, persisted "did I already try this recently"
    cache (removed entirely, direct user feedback, 2026-11-24: "kunnen we
    dit niet slimmer maken? zodat we die cache niet nodig hebben?") -- no
    local state needed at all once the live source of truth is checked
    directly.

    A plain REST list of every still-open firmware-version-labeled issue
    (not GitHub's own search API, whose index lags behind a just-created
    issue), scanned for one whose body mentions all three fields in
    exactly the shape firmware_version_issue_body.py's own _field produces
    -- cheap and well within normal REST rate limits, since only ever a
    handful of these are open at any moment (each one normally closes
    within seconds of being opened). Raises on a genuine fetch failure,
    same as async_submit_firmware_version itself -- the caller already
    wraps this in the same try/except."""
    session = async_get_clientsession(hass)
    async with session.get(
        f"{_ISSUES_URL}?labels=firmware-version&state=open&per_page=100",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"},
        timeout=10,
    ) as response:
        response.raise_for_status()
        issues = await response.json(content_type=None)
    for issue in issues:
        body = issue.get("body") or ""
        if (
            f"### Manufacturer\n\n{manufacturer}\n" in body
            and f"### Model\n\n{model}\n" in body
            and f"### Raw OTA version\n\n{raw_version}\n" in body
        ):
            return True
    return False
