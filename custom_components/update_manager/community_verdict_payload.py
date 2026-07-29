"""Pure, HA-independent extraction over an already-fetched community-votes
to_version payload, split out from community_verdict.py specifically so this
stays unit-testable without a live hass, same reasoning as semver.py/
staging.py/hacs_identity.py/vote_issue_body.py being their own dependency-
free modules.

A vote/verdict is identified by the exact version jump (from_version ->
to_version), not the destination version alone (see hacs_identity.py's own
docstring for why). community-votes stores every jump landing on the same
to_version in one shared file (shape: {"jumps": {"<from_version>": {"votes":
{...}, "verdict": {...}}, ...}}) -- every function here answers one specific
question about that same already-fetched payload (my own jump's verdict, a
specific username's vote, the trusted-voter check, other jumps to the same
destination), so community_verdict.py only ever needs to fetch it once per
call.
"""
from __future__ import annotations

from typing import Any

# Other jumps landing on the same destination version, shown in the dialog
# below the user's own jump (direct user feedback, 2026-07-24: "als
# belangrijkste dan natuurlijk de sprong die ik zelf ga nemen") -- capped so
# a destination version with many rated jumps doesn't turn into a wall of
# text in a compact dialog section.
MAX_OTHER_JUMPS = 5

# Same reasoning as MAX_OTHER_JUMPS above, applied to problematic_reasons_from_payload.
MAX_PROBLEMATIC_REASONS = 5


def verdict_from_payload(payload: dict[str, Any] | None, from_version: str) -> dict[str, Any] | None:
    """My own jump's aggregate verdict from an already-fetched to_version
    payload, or None if that jump has no votes at all yet."""
    if not payload:
        return None
    return payload.get("jumps", {}).get(from_version, {}).get("verdict")


def my_vote_from_payload(payload: dict[str, Any] | None, from_version: str, username: str) -> str | None:
    """One specific username's own verdict for one specific jump, from an
    already-fetched to_version payload."""
    if not payload:
        return None
    votes = payload.get("jumps", {}).get(from_version, {}).get("votes", {})
    entry = votes.get(username)
    return entry.get("verdict") if entry else None


def trusted_vote_from_payload(
    payload: dict[str, Any] | None, from_version: str, trusted_voters: list[str]
) -> tuple[str | None, list[str]]:
    """Every configured trusted username's own vote for my exact jump,
    aggregated the same asymmetric-safety way this project already resolves
    the *aggregate* auto-install quorum (FUTURE.md's own point 5): any
    "problematic" among them wins outright, even if others among them voted
    "healthy" -- only if none of them did, and at least one voted "healthy",
    does that apply instead. A purely synchronous lookup over an already-
    fetched payload (changed 2026-07-24: used to be its own asyncio.gather
    over N separate per-username requests, now every username's vote for
    this jump already lives in the one payload community_verdict.py already
    fetched). (None, []) with no lookup at all when no trusted voter is
    configured."""
    if not trusted_voters or not payload:
        return None, []
    votes = payload.get("jumps", {}).get(from_version, {}).get("votes", {})
    voted = {username: votes[username]["verdict"] for username in trusted_voters if username in votes}
    problematic = [username for username, verdict in voted.items() if verdict == "problematic"]
    if problematic:
        return "problematic", problematic
    healthy = [username for username, verdict in voted.items() if verdict == "healthy"]
    if healthy:
        return "healthy", healthy
    return None, []


def other_jumps_from_payload(payload: dict[str, Any] | None, from_version: str) -> list[dict[str, Any]]:
    """Every other jump landing on this same destination version (my own
    from_version excluded), sorted by total vote count descending and
    capped at MAX_OTHER_JUMPS -- the dialog's own supplementary "how did
    other jumps to this version go" section, direct user feedback,
    2026-07-24. Empty when there simply aren't any yet (a brand new
    destination version, or one only my own jump has been rated for) --
    the dialog shows nothing at all in that case, not an empty-state
    message."""
    if not payload:
        return []
    others = []
    for jump_from_version, jump in payload.get("jumps", {}).items():
        if jump_from_version == from_version:
            continue
        verdict = jump.get("verdict")
        if not verdict:
            continue
        others.append(
            {
                "from_version": jump_from_version,
                "healthy_count": verdict.get("healthy_count", 0),
                "problematic_count": verdict.get("problematic_count", 0),
                "quorum_reached": verdict.get("quorum_reached", False),
                "auto_install_eligible": verdict.get("auto_install_eligible", False),
            }
        )
    others.sort(key=lambda j: j["healthy_count"] + j["problematic_count"], reverse=True)
    return others[:MAX_OTHER_JUMPS]


def _reason_entry(username: str, entry: dict[str, Any]) -> dict[str, Any]:
    """The shared shape both problematic_reasons_from_payload and
    my_problematic_reason_from_payload return per voter."""
    return {
        "username": username,
        "reason_category": entry.get("reason_category"),
        "notes": entry.get("notes"),
        "link": entry.get("link"),
        "created_at": entry.get("created_at"),
    }


def problematic_reasons_from_payload(
    payload: dict[str, Any] | None, from_version: str, *, exclude_username: str | None = None
) -> list[dict[str, Any]]:
    """Every *other* problematic voter's own reason for my exact jump, most
    recent first, capped like other_jumps_from_payload above.
    reason_category/notes/link are collected at submission time
    (vote_issue_body.py, the panel's own vote dialog) and are persisted
    per-voter upstream (community-votes' process-vote.yml writes them
    straight into each jump.votes[username] entry), but no function in
    this module used to read anything past the bare verdict string -- a
    vote's reason was write-only from this integration's own perspective.
    Direct user feedback, 2026-07-29: "ik zie in de interface nergens de
    reden staan. Dat had ik wel verwacht."

    exclude_username is filtered out *before* sorting/capping, not after
    (found by review, 2026-07-29): filtering the caller's own username out
    of an already-capped result could silently drop it entirely whenever
    MAX_PROBLEMATIC_REASONS or more other people voted more recently --
    my_reason would then come back empty even though a real reason exists,
    the exact duplication bug this same field was built to fix in the
    first place. Use my_problematic_reason_from_payload below for that
    caller's own reason instead, a direct lookup with no cap to fall
    afoul of."""
    if not payload:
        return []
    votes = payload.get("jumps", {}).get(from_version, {}).get("votes", {})
    reasons = [
        _reason_entry(username, entry)
        for username, entry in votes.items()
        if entry.get("verdict") == "problematic" and username != exclude_username
    ]
    reasons.sort(key=lambda r: r["created_at"] or "", reverse=True)
    return reasons[:MAX_PROBLEMATIC_REASONS]


def my_problematic_reason_from_payload(
    payload: dict[str, Any] | None, from_version: str, username: str | None
) -> dict[str, Any] | None:
    """One specific username's own problematic-vote reason for my exact
    jump, or None if they have no vote at all or it isn't problematic --
    a direct lookup, deliberately independent of
    problematic_reasons_from_payload's own top-N cap (see that function's
    own docstring for why: capping first and filtering for "mine" after
    could silently lose your own reason once enough other, more recent
    votes exist)."""
    if not payload or not username:
        return None
    votes = payload.get("jumps", {}).get(from_version, {}).get("votes", {})
    entry = votes.get(username)
    if not entry or entry.get("verdict") != "problematic":
        return None
    return _reason_entry(username, entry)
