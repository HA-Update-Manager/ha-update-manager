"""Finds the one external (not an entity's own repo) GitHub release
referenced inside a piece of release-notes text, and resolves it to a
fetchable release tag.

A faithful port of update-manager-panel.js's own
_findEmbeddedUpstreamRelease (see that function's own comment for the two
real confirmed examples this was built from: a Zigbee2MQTT add-on's own
release notes linking straight to Koenkk/zigbee2mqtt's exact release, and a
Mealie add-on's own release notes linking to mealie-recipes/mealie's
general releases page with no specific tag at all). Kept pure and
HA-independent, same reasoning as changelog_trim.py -- see that module's
own docstring.
"""
from __future__ import annotations

import re
from typing import NamedTuple

_LINK_RE = re.compile(r"https?://[^\s)]+")
_RELEASE_RE = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/releases(?:/(?:tag/)?([^/]+))?")
# Also recognizes github.com/OWNER/REPO/blob/BRANCH/CHANGELOG.md, not just
# /releases/... -- a real matterbridge-home-assistant-addon example links a
# sub-dependency's own changelog this way. Carries no tag of its own (a
# blob link has no release tag in it at all).
_CHANGELOG_BLOB_RE = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/blob/[^/]+/CHANGELOG\.md", re.IGNORECASE)


class EmbeddedUpstreamRelease(NamedTuple):
    owner: str
    repo: str
    # None whenever the embedded link names no specific tag at all (a bare
    # releases-listing link, or a CHANGELOG.md blob link) -- the caller's
    # own "current version being installed" is tried as a fallback tag
    # instead, since an add-on's own version number frequently *is* the
    # upstream tag verbatim.
    tag: str | None


def _strip_v_prefix(version: str) -> str:
    return re.sub(r"^[vV]", "", version, count=1)


def find_embedded_upstream_release(
    notes: str | None, own_owner: str | None, own_repo: str | None, from_version: str | None
) -> EmbeddedUpstreamRelease | None:
    """None whenever no such link is found, or more than one *distinct*
    repo is referenced -- several dependency bumps mentioned at once is a
    real, common shape too, and guessing which one is "the" upstream
    project among several would be exactly the kind of unreliable guess
    this whole feature otherwise avoids.

    own_owner/own_repo (this entity's own repo, parsed from its own
    release_url) are excluded so a repo's own release notes linking back
    to its own earlier release is never mistaken for "an upstream
    project". from_version (this entity's own previous version) catches
    the same self-reference a second way, for whenever own_owner/own_repo
    aren't even available to check against in the first place (a
    Supervisor add-on's own update entity never sets release_url at all).

    A link that matches neither GitHub shape (an upstream project's own
    changelog mirrored to a custom domain, say) still can't be resolved to
    a repo -- there's no reliable, general way to turn an arbitrary docs
    domain into "this is really this GitHub repo" without guessing. But it
    still counts as *a* distinct external reference here (keyed by its own
    URL, unresolved), so an entry mentioning both this kind of link and a
    real, resolvable GitHub one isn't mistaken for "exactly one" -- picking
    the resolvable one anyway would show the *wrong* (less relevant)
    project's notes with no indication anything was left out, worse than
    showing nothing."""
    if not notes:
        return None
    normalized_from_version = _strip_v_prefix(from_version).lower() if from_version else None
    seen: dict[str, EmbeddedUpstreamRelease | None] = {}
    for match in _LINK_RE.finditer(notes):
        url = match.group(0)
        release_match = _RELEASE_RE.match(url)
        blob_match = None if release_match else _CHANGELOG_BLOB_RE.match(url)
        if release_match is None and blob_match is None:
            seen.setdefault(url, None)
            continue
        m = release_match or blob_match
        owner, repo = m.group(1), m.group(2)
        tag = m.group(3) if release_match else None
        if own_owner and own_repo and owner.lower() == own_owner.lower() and repo.lower() == own_repo.lower():
            continue
        # A link whose own tag is exactly this entity's own previous
        # version (from_version) is a "Changes since {from_version}"
        # self-reference to this same entity's own prior release, not a
        # genuine external upstream project.
        if tag and normalized_from_version and _strip_v_prefix(tag).lower() == normalized_from_version:
            continue
        key = f"{owner.lower()}/{repo.lower()}"
        # "latest" (github.com/owner/repo/releases/latest, a real, common
        # GitHub URL shape that always redirects to whatever's newest)
        # isn't a real tag at all -- treated the same as no tag.
        normalized_tag = tag if tag and tag.lower() != "latest" else None
        seen.setdefault(key, EmbeddedUpstreamRelease(owner=owner, repo=repo, tag=normalized_tag))
    if len(seen) != 1:
        return None
    return next(iter(seen.values()))
