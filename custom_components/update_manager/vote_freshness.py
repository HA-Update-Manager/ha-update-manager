"""Pure, HA-independent staleness check for a remembered vote, split out
from my_votes.py specifically so this stays unit-testable without a live
hass, same reasoning as semver.py/staging.py/hacs_identity.py/
vote_issue_body.py/community_verdict_payload.py being their own
dependency-free modules.
"""
from __future__ import annotations

from datetime import datetime, timedelta


def is_vote_stale(voted_at: str | None, now: datetime, grace_period: timedelta) -> bool:
    """True once a remembered vote is old enough that websocket_api.py's own
    verdict_for_version handler may safely cross-check it against live
    community-votes data and forget it if that data no longer confirms it
    (see MyVotesManager.is_stale's own docstring for the full reasoning: a
    vote just cast is expected to be briefly missing from that live data
    while community-votes' own Action is still processing it, and must keep
    being trusted regardless until it's had time to catch up).

    No voted_at at all (a pre-2026-08-01 entry, from before this field
    existed) is always stale: there's nothing to compare against, and
    treating an unknown age as "definitely old enough" is the same
    graceful-degradation choice this module already makes elsewhere for a
    stored jump_key that simply predates a given feature."""
    if voted_at is None:
        return True
    # voted_at is always dt_util.utcnow().isoformat() as stored by
    # MyVotesManager.async_remember -- a standard ISO 8601 string with an
    # explicit UTC offset, which datetime.fromisoformat parses directly, no
    # need for HA's own dt_util here (keeping this module HA-independent).
    return now - datetime.fromisoformat(voted_at) > grace_period
