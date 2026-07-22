"""Pure, HA-independent resolution of which community-votes path an update
entity belongs under (see resolve_votes_path), split out from
community_verdict.py specifically so this stays unit-testable without a live
hass, same reasoning as semver.py/staging.py being their own dependency-free
modules.

Found live 2026-07-22, testing against ha-update-manager's own update
entity: GitHub accepts both `releases/tag/<tag>` (the canonical form) and a
shorter `releases/<tag>` (no `/tag/` segment) as real, working URLs, and
different integrations' own update entities are free to set either shape in
`release_url`, it's an opaque attribute, nothing enforces the canonical one.
Both are matched here (extract_hacs_identity).
"""
from __future__ import annotations

import re

from .semver import strip_version_prefix

_RELEASE_URL_RE = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/releases/(?:tag/)?(.+)$")


def extract_hacs_identity(release_url: str | None) -> tuple[str, str, str] | None:
    """(owner, repo, version) from a GitHub release URL, or None if
    release_url is missing or doesn't match that shape at all. release_url
    is an opaque attribute set by whatever integration backs an update
    entity, not guaranteed to look like a GitHub release URL at all, so a
    non-match is expected/normal, never an error.

    The version itself is normalized the same way semver.py already does
    (strip_version_prefix, shared rather than duplicated), so a release
    tagged "v1.2.3" and a human-typed "1.2.3" land on the exact same
    community-votes path either way. community-votes' own process-vote.yml
    normalizes the same way independently (a separate repo, can't literally
    share this code); keep both in sync if this rule ever changes."""
    if not release_url:
        return None
    match = _RELEASE_URL_RE.match(release_url)
    if not match:
        return None
    return match.group(1), match.group(2), strip_version_prefix(match.group(3))


# Found by review, 2026-07-22: Home Assistant Core/Supervisor/OS's own
# release_url is a real, ordinary-looking GitHub release URL too (e.g.
# https://github.com/home-assistant/core/releases/tag/2026.7.3), so it
# matched extract_hacs_identity's fully generic regex just as readily as any
# HACS-installed integration and was silently filed under votes/hacs/... --
# the wrong category path, per community-votes' own reserved
# votes/home-assistant/<core|supervisor|os>/... structure (see FUTURE.md).
# These three entity_ids are HA core's own fixed, well-known ones (confirmed
# against real bug reports/service-call examples referencing them, not
# guessed).
_HOME_ASSISTANT_COMPONENT_BY_ENTITY_ID = {
    "update.home_assistant_core_update": "core",
    "update.home_assistant_supervisor_update": "supervisor",
    "update.home_assistant_operating_system_update": "os",
}


def resolve_votes_path(entity_id: str, release_url: str | None, latest_version: str) -> str | None:
    """The `votes/<category>/...` path this entity belongs under, or None
    if it can't be identified at all.

    Home Assistant Core/Supervisor/OS are checked first, by fixed entity_id
    (see _HOME_ASSISTANT_COMPONENT_BY_ENTITY_ID's own comment): their
    release_url would otherwise match the generic HACS shape below just as
    readily and land in the wrong category. Uses latest_version directly for
    these three, not release_url's own version, so this doesn't depend on
    their release_url happening to look like a GitHub release URL at all,
    unlike the HACS case below where owner/repo can only come from there.

    Devices/apps (the other two categories community-votes' own structure
    reserves) aren't resolved at all yet, real, separate design work per the
    approved plan for this feature."""
    component = _HOME_ASSISTANT_COMPONENT_BY_ENTITY_ID.get(entity_id)
    if component is not None:
        return f"home-assistant/{component}/{strip_version_prefix(latest_version)}"

    identity = extract_hacs_identity(release_url)
    if identity is None:
        return None
    owner, repo, version = identity
    return f"hacs/{owner}/{repo}/{version}"
