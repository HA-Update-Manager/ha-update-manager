"""Pure, HA-independent extraction of a (owner, repo, version) identity from
a GitHub release URL, split out from community_verdict.py specifically so it
stays unit-testable without a live hass, same reasoning as semver.py/
staging.py being their own dependency-free modules.

Found live 2026-07-22, testing against ha-update-manager's own update
entity: GitHub accepts both `releases/tag/<tag>` (the canonical form) and a
shorter `releases/<tag>` (no `/tag/` segment) as real, working URLs, and
different integrations' own update entities are free to set either shape in
`release_url`, it's an opaque attribute, nothing enforces the canonical one.
Both are matched here.
"""
from __future__ import annotations

import re

_RELEASE_URL_RE = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/releases/(?:tag/)?(.+)$")

# Community-votes' own process-vote.yml normalizes the same way (strips a
# leading v/V before a digit) before building a vote's path, so a
# human-typed "1.2.3" and a release-URL-derived "v1.2.3" land on the exact
# same path either way, regardless of which side happens to include the
# prefix. Keep both normalizations in sync if this ever changes.
_V_PREFIX_RE = re.compile(r"^[vV](\d.*)$")


def _normalize_version(version: str) -> str:
    match = _V_PREFIX_RE.match(version)
    return match.group(1) if match else version


def extract_hacs_identity(release_url: str | None) -> tuple[str, str, str] | None:
    """(owner, repo, version) from a GitHub release URL, or None if
    release_url is missing or doesn't match that shape at all. release_url
    is an opaque attribute set by whatever integration backs an update
    entity, not guaranteed to look like a GitHub release URL at all, so a
    non-match is expected/normal, never an error."""
    if not release_url:
        return None
    match = _RELEASE_URL_RE.match(release_url)
    if not match:
        return None
    return match.group(1), match.group(2), _normalize_version(match.group(3))
