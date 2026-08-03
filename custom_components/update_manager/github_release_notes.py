"""Pure, HA-independent GitHub release-URL parsing for the release-notes
fallback (direct user feedback, 2026-08-01: HACS's own update entities
regularly have nothing to show -- async_release_notes() returns None
whenever pending_restart is still true, or the installed version isn't in
HACS's own published_tags -- even though a real GitHub release with real
notes exists at release_url the whole time).

Split out from hacs_identity.py despite reusing the same URL shape (and its
own _RELEASE_URL_RE, imported below rather than redefined -- same regex,
one definition): that module's own extract_hacs_identity normalizes the
version (strips a "v" prefix, see semver.py) since it only needs the
version to build a community-votes path. This module needs the *exact*,
unmodified tag as it appears in the URL, since that's passed straight to
GitHub's own `/releases/tags/{tag}` API, which requires an exact match -- a
normalized tag would 404 against a repo that actually tags with a "v"
prefix.
"""
from __future__ import annotations

from typing import Any

from .hacs_identity import _RELEASE_URL_RE
from .semver import strip_version_prefix


def parse_release_url(url: str | None) -> tuple[str, str, str] | None:
    """(owner, repo, tag) parsed straight from url, tag left exactly as
    written (no "v"-prefix stripping, unlike hacs_identity.py's own
    extract_hacs_identity). None if url is missing or doesn't match this
    shape at all -- release_url is an opaque attribute set by whatever
    entity happens to have one, not guaranteed to look like a GitHub release
    URL at all, so a non-match is expected/normal, never an error (same
    reasoning as extract_hacs_identity's own docstring)."""
    if not url:
        return None
    match = _RELEASE_URL_RE.match(url)
    if not match:
        return None
    return match.group(1), match.group(2), match.group(3)


def _find_release_index(releases: list[dict[str, Any]], version: str) -> int | None:
    """Index of the release whose own tag_name matches `version` once both
    are normalized (strip_version_prefix) -- shared by compile_release_range
    (needs the index, to slice the walk from there) and find_release_by_version
    (needs the release itself), so the matching rule only ever needs
    updating in one place, not two independently-written scans."""
    normalized = strip_version_prefix(version)
    return next(
        (i for i, release in enumerate(releases) if strip_version_prefix(release.get("tag_name", "")) == normalized),
        None,
    )


def compile_release_range(
    releases: list[dict[str, Any]], from_version: str, target_tag: str
) -> str | None:
    """Every release's own body, from target_tag down to (not including)
    from_version, newest first, each under its own "## {tag_name}" heading --
    direct user feedback, 2026-08-01: skipping straight from an old
    installed version to a much newer one otherwise only ever shows the
    single newest release's own notes, silently missing whatever changed in
    every version in between (same gap HACS's own async_release_notes()
    already closes when it can, see custom_components/hacs/update.py's own
    "Compile release notes from installed version up to the latest" -- this
    is that same idea, for the cases where HACS itself can't, or for
    entities that never had this ability at all, like Home Assistant
    Supervisor's own update entity).

    `releases` is expected newest-first, GitHub's own default order for
    `GET /repos/{owner}/{repo}/releases`, not re-sorted here. Both
    target_tag and from_version are compared with a leading "v" stripped
    from either side (strip_version_prefix, same normalization semver.py
    already applies everywhere else in this project) -- release tags in the
    wild are inconsistent about this even within the same org (confirmed
    2026-07-31: home-assistant/core tags bare "2026.7.4", hassio-addons
    tags "v24.0.1"), and comparing raw strings would silently miss a real
    match.

    None if target_tag isn't found in releases at all (nothing to compile,
    caller falls back to fetching just the single target release instead);
    still returns whatever it has if from_version is never found before the
    list runs out (an old install predating what GitHub's own default
    per_page window returns, or from_version simply doesn't correspond to a
    real tag) -- better an incomplete-but-real range than nothing.

    Skipped releases flagged `prerelease` (GitHub's own field on every
    entry from GET /repos/{owner}/{repo}/releases) are left out of the
    walk entirely -- direct user feedback, 2026-08-01: a normal stable-to-
    stable jump otherwise dragged in every beta/rc changelog GitHub happened
    to tag in between, which is never what actually got installed along the
    way. target_tag itself is always included even if it's a prerelease --
    that's a real, deliberate jump to that exact beta/rc, not a skipped
    stepping stone, so it must never be filtered out.

    A downgrade (from_version newer than target_tag) shows target_tag, every
    real release in between, and from_version itself, oldest first -- the
    opposite reading order from a normal upgrade. Direct user feedback,
    2026-08-02 (two rounds): a real downgrade first exposed that this
    function's walk direction only makes sense "forward" (from a newer
    target_tag down through older, skipped releases, stopping once it
    reaches the older from_version it started from) -- for a downgrade,
    from_version sits *before* target_tag in this newest-first list, not
    after it, so the walk's own stop condition was never reached and it
    silently ran all the way to the very first release this repo ever
    tagged. That was first fixed by only ever compiling target_tag's own
    single release for a downgrade -- correct, but then reconsidered:
    a downgrade is really "what am I giving up by stepping back", which is
    exactly what the versions between target_tag and from_version (from_version
    included) describe, so it's more useful to show all of them, just read
    oldest-to-newest (you land on target_tag first, then read forward
    through what you're losing, ending on from_version, the version you were
    just on) instead of upgrade's newest-first order. Unlike a normal
    upgrade, from_version is deliberately *included* here (an upgrade
    excludes it, since that's what the reader already has installed and
    knows) -- for a downgrade it's the version being left behind, which is
    exactly the point of showing this at all.

    Detected by comparing each version's own index in `releases` (this
    project has no general version-number comparator, and doesn't need one
    here: GitHub's own newest-first order already encodes exactly the
    ordering this needs) -- if from_version's index is found and comes
    *before* target_tag's own, this is a downgrade. Both endpoints
    (target_tag and from_version) are always included even if flagged
    prerelease, same reasoning as target_tag's own rule for a normal
    upgrade below -- a real, deliberate jump to/from an exact beta/rc is
    never a skipped stepping stone; only releases strictly between the two
    endpoints are subject to the usual prerelease skip."""
    normalized_from = strip_version_prefix(from_version)
    start_index = _find_release_index(releases, target_tag)
    if start_index is None:
        return None
    from_index = _find_release_index(releases, from_version)
    if from_index is not None and from_index < start_index:
        window = list(reversed(releases[from_index : start_index + 1]))
        last = len(window) - 1
        sections = []
        for offset, release in enumerate(window):
            if 0 < offset < last and release.get("prerelease"):
                continue
            body = release.get("body")
            if body:
                sections.append(f"## {release.get('tag_name')}\n\n{body}")
        return "\n\n".join(sections) if sections else None
    sections = []
    for offset, release in enumerate(releases[start_index:]):
        if strip_version_prefix(release.get("tag_name", "")) == normalized_from:
            break
        if offset > 0 and release.get("prerelease"):
            continue
        body = release.get("body")
        if body:
            sections.append(f"## {release.get('tag_name')}\n\n{body}")
    return "\n\n".join(sections) if sections else None


def find_release_by_version(releases: list[dict[str, Any]], version: str) -> dict[str, Any] | None:
    """The release whose own tag_name matches `version` once both are
    normalized (strip_version_prefix, same reasoning as compile_release_range
    above). None if not found -- version older than what the caller's own
    page/limit returned, or simply doesn't correspond to a real tag.

    Direct user feedback, 2026-08-01, on a real downgrade (2.0 -> 1.0): the
    entity's own release_url attribute reflects "latest available", not
    "what actually got installed" -- true for HACS specifically (its own
    release_url property is built from display_available_version, never
    installed_version, confirmed against its real source), and downgrades
    are a genuinely common flow here, not a rare edge case (the whole
    community-voting feature exists so people can downgrade after finding a
    problematic update). Used to find the *real* tag for whatever version
    was actually installed, so the release-notes fallback and the "Open
    release announcement" link stop describing a completely different,
    newer release than the one the user actually ended up on."""
    index = _find_release_index(releases, version)
    return releases[index] if index is not None else None
