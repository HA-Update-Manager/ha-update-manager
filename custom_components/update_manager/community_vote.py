"""Submits a vote to community-votes as a GitHub Issue, mirroring
community_verdict.py's own shape but for writing (confirmed via a live
test: any GitHub account can open an issue on a public
repo the target App is installed on, regardless of collaborator status, so
no fork/App-install is needed on the voter's side, only the linked account's
own access token, see github_auth.py).

The issue body itself is built by vote_issue_body.py, kept pure/HA-
independent and unit-tested there rather than here, same reasoning as
hacs_identity.py.
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .hacs_identity import ResolvedIdentity
from .vote_issue_body import Verdict, build_issue_body

_ISSUES_URL = "https://api.github.com/repos/HA-Update-Manager/community-votes/issues"


async def async_submit_vote(
    hass: HomeAssistant,
    access_token: str,
    identity: ResolvedIdentity,
    verdict: Verdict,
    reason_category: str | None,
    notes: str | None,
    link: str | None,
) -> None:
    """Raises on failure (a non-2xx response, a network error): the caller
    (websocket_api.py's own vote handler) turns that into a clear,
    user-visible error, never a silent no-op.

    No "labels" field here (found live, 2026-08-15) -- community-votes' own
    process-vote.yml always applies the "vote" label itself afterward
    regardless (a harmless no-op if it's already there, see that workflow's
    own comment), and isn't gated on the label being present to begin with
    (it decides from the body's own shape instead). Sending it here had no
    effect for a real voter anyway (GitHub's own issue-creation API silently
    drops labels from anyone without push access, community-votes'
    process-vote.yml's own issue #36), it only mattered for a repo owner's
    own test votes (push access does accept it), where the one visible
    effect was the issue's "labeled" timeline entry crediting the voter
    instead of github-actions[bot] -- purely cosmetic, and inconsistent
    with every other voter's own issue."""
    body = build_issue_body(identity, verdict, reason_category, notes, link)
    session = async_get_clientsession(hass)
    async with session.post(
        _ISSUES_URL,
        json={"title": "[vote]", "body": body},
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"},
        timeout=10,
    ) as response:
        response.raise_for_status()
