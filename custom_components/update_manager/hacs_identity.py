"""Pure, HA-independent resolution of which community-votes category/path an
update entity belongs under (see resolve_identity), split out from
community_verdict.py/community_vote.py specifically so this stays
unit-testable without a live hass, same reasoning as semver.py/staging.py
being their own dependency-free modules.

Found live 2026-07-22, testing against ha-update-manager's own update
entity: GitHub accepts both `releases/tag/<tag>` (the canonical form) and a
shorter `releases/<tag>` (no `/tag/` segment) as real, working URLs, and
different integrations' own update entities are free to set either shape in
`release_url`, it's an opaque attribute, nothing enforces the canonical one.
Both are matched here (extract_hacs_identity).
"""
from __future__ import annotations

import re
from typing import NamedTuple

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
# votes/home-assistant/<core|supervisor|os>/... structure.
# These three entity_ids are HA core's own fixed, well-known ones (confirmed
# against real bug reports/service-call examples referencing them, not
# guessed).
_HOME_ASSISTANT_COMPONENT_BY_ENTITY_ID = {
    "update.home_assistant_core_update": "core",
    "update.home_assistant_supervisor_update": "supervisor",
    "update.home_assistant_operating_system_update": "os",
}


def corrected_release_url(entity_id: str, native_release_url: str | None, latest_version: str) -> str | None:
    """The release_url a Core update entity's own dialog/History entry
    should actually use -- corrects for a real bug in Core's own update
    entity (SupervisorCoreUpdateEntity.release_url, hassio/update.py): it's
    a fixed "https://www.home-assistant.io/latest-release-notes/" (or
    "rc." for a beta build), always the *current* latest notes regardless
    of which version this call is actually about (verified directly
    against home-assistant/core's own source, 2026-07-31) -- fine, by
    coincidence, for a pending update (that genuinely is the latest), but
    actively wrong for a History entry of an older install, and not a real
    github.com URL at all so nothing that expects one (e.g. the GitHub
    release-notes fallback fetch) can do anything useful with it either.

    Built ourselves instead, from home-assistant/core's own GitHub
    releases: every tagged release (stable and beta alike) uses the
    version string verbatim as its tag, no "v" prefix, no reformatting
    (confirmed live against 4 real releases spanning 2024.1.0 through
    2026.8.0b3, 2026-07-31, not assumed from a single lucky example). Dev
    builds ("2026.8.0.dev...") are never tagged there at all (confirmed: a
    404), so those fall through to native_release_url unchanged rather
    than linking to a release that doesn't exist.

    OS/Supervisor's own native release_url (hassio/update.py's own
    SupervisorOS/SupervisorSupervisorUpdateEntity) is already a real,
    version-specific github.com/home-assistant/{operating-system,
    supervisor}/releases/tag/{version} URL, so those (and every entity_id
    that isn't one of HA's own three fixed ones at all) pass
    native_release_url straight through unchanged -- only Core is
    actually broken."""
    to_version = strip_version_prefix(latest_version)
    if _HOME_ASSISTANT_COMPONENT_BY_ENTITY_ID.get(entity_id) != "core" or ".dev" in to_version:
        return native_release_url
    return f"https://github.com/home-assistant/core/releases/tag/{to_version}"


class ResolvedIdentity(NamedTuple):
    """Everything both the read side (community_verdict.py, needs only
    .to_version_path plus from_version as a lookup key) and the write side
    (community_vote.py, needs the individual fields to build a vote's issue
    body) need, computed once instead of twice. Exactly one of component/
    owner_repo/manufacturer_model/app_slug is set, matching which category
    this identity is. manufacturer_model is already the joined "manufacturer/
    model" string (found by review: every consumer -- to_version_path below,
    vote_issue_body.py's own "Manufacturer/model" field -- immediately
    joined the two, keeping them as separate fields just duplicated that
    join).

    A vote/verdict is identified by the exact version jump (from_version ->
    to_version), not the destination version alone (changed 2026-07-24,
    direct user feedback: going from 0.1.0 to 3.5.2 -- possibly skipping
    several breaking changes -- is a fundamentally different risk than going
    from 3.5.1 to 3.5.2, even though both land on the same version). Both
    are required fields here -- a jump without a "from" isn't a valid
    identity under this model. from_version is never part of any *path*
    though (see to_version_path below): community-votes stores every jump
    landing on the same destination in one shared file, so from_version is
    purely a dict key used after fetching that one file, not a path
    segment."""

    category: str
    to_version: str
    from_version: str
    component: str | None = None
    owner_repo: str | None = None
    manufacturer_model: str | None = None
    app_slug: str | None = None
    # The exact release_url this owner_repo/to_version pair was resolved
    # from (hacs category only, see resolve_identity below) -- kept so
    # vote_issue_body.py can link "Owner/repo" straight to the release being
    # voted on. Safe to reuse as-is: callers already resolve the release_url
    # that matches this exact version before calling resolve_identity (see
    # websocket_api.py's own _release_url_for_version, which checks the
    # matching install_log entry first, not just the entity's current live
    # state), so this is never a stale/wrong-version URL, just sometimes
    # absent (older install_log entries predating that tracking).
    release_url: str | None = None

    @property
    def jump_key(self) -> str:
        """A single string uniquely identifying this exact jump -- for
        anything that needs one opaque key rather than the two separate
        fields (my_votes.py's own local Store, keyed by this instead of
        entity_id/version separately, exactly like it was keyed by the old
        single-version votes_path before this session's jump-based
        redesign). "::" can't appear in a real path segment, so this can't
        collide with a to_version_path for a different identity/version
        that happens to share a from_version string."""
        return f"{self.to_version_path}::{self.from_version}"

    @property
    def to_version_path(self) -> str:
        if self.category == "home-assistant":
            return f"home-assistant/{self.component}/{self.to_version}"
        if self.category == "hacs":
            return f"hacs/{self.owner_repo}/{self.to_version}"
        if self.category == "devices":
            return f"devices/{self.manufacturer_model}/{self.to_version}"
        return f"apps/{self.app_slug}/{self.to_version}"


def resolve_identity(
    entity_id: str,
    release_url: str | None,
    latest_version: str,
    installed_version: str,
    *,
    is_hacs_entity: bool = False,
    device_manufacturer: str | None = None,
    device_model: str | None = None,
    app_slug: str | None = None,
) -> ResolvedIdentity | None:
    """Which category this entity belongs under, plus the specific identity
    fields for it, or None if it can't be identified at all.

    Home Assistant Core/Supervisor/OS are checked first, by fixed entity_id
    (see _HOME_ASSISTANT_COMPONENT_BY_ENTITY_ID's own comment): their
    release_url would otherwise match the generic HACS shape below just as
    readily and land in the wrong category. Uses latest_version directly for
    these three, not release_url's own version, so this doesn't depend on
    their release_url happening to look like a GitHub release URL at all,
    unlike the HACS case below where owner/repo can only come from there.

    installed_version is normalized the exact same way latest_version is
    (strip_version_prefix) -- must not be skipped: an update entity's own
    installed_version attribute is just as likely to carry a stray "v"
    prefix as latest_version is, and skipping normalization here would
    silently split what's actually the same jump into two different
    community-votes entries. Callers are expected to already have filtered
    out a None installed_version before calling this (same "can't identify
    this at all" treatment as a missing release_url), so this takes a plain
    str, not Optional.

    is_hacs_entity, device_manufacturer/device_model, and app_slug are all
    pre-resolved by the caller (device_identity.py), not looked up here:
    this module stays free of any homeassistant import, same reasoning as
    semver.py/staging.py/rollout.py (see each one's own docstring), and
    entity_registry/device_registry lookups need a real hass.

    is_hacs_entity gates the HACS branch entirely (found live, 2026-07-22,
    real bug hit on an ESPHome device's update entity): release_url merely
    *looking* like a genuine GitHub release URL is not enough. ESPHome (and
    presumably other built-in integrations) can set a perfectly real
    https://github.com/... release_url pointing at their own upstream
    project, with nothing HACS-related about it at all, and that entity
    would otherwise get silently misidentified as if it were a HACS-
    installed integration. Verified against hacs/integration's own source
    (custom_components/hacs/update.py): every genuinely HACS-installed
    repo's update entity is created by HacsRepositoryUpdateEntity, which
    belongs to HACS's own integration domain ("hacs") -- device_identity.py
    checks that via entity_registry before ever passing is_hacs_entity=True.

    Passing a genuine manufacturer/model is itself the scope decision
    (approved 2026-07-22): only real, vendor-issued firmware (Zigbee/
    Z-Wave-style, identical regardless of which HA integration manages the
    device) belongs in that category. ESPHome/Tasmota-style self-compiled
    firmware must never be passed in there, since two users' "same board
    model" can run completely different, incomparable custom firmware
    there -- that exclusion happens in device_identity.py, not here."""
    from_version = strip_version_prefix(installed_version)
    component = _HOME_ASSISTANT_COMPONENT_BY_ENTITY_ID.get(entity_id)
    if component is not None:
        to_version = strip_version_prefix(latest_version)
        # See corrected_release_url's own docstring: Core's own native
        # release_url is a real bug (always "latest", never version-
        # specific), OS/Supervisor's isn't -- that function already knows
        # the difference, shared here rather than re-deriving it.
        return ResolvedIdentity(
            "home-assistant",
            to_version,
            from_version,
            component=component,
            release_url=corrected_release_url(entity_id, release_url, latest_version),
        )

    identity = extract_hacs_identity(release_url) if is_hacs_entity else None
    if identity is not None:
        owner, repo, _url_version = identity
        # latest_version (the version this call is actually about), not
        # _url_version (whatever tag happens to be embedded in release_url)
        # -- found live, 2026-07-22: a real HACS entity's release_url isn't
        # guaranteed to be *for* the exact version being voted on/checked
        # (e.g. it can still point at the newest available release even
        # while resolving an older, already-installed History entry), so
        # trusting it for the version silently misattributed a vote to the
        # wrong version. release_url is only ever used here to find the
        # owner/repo, never the version -- still stored below (see
        # ResolvedIdentity.release_url's own comment) since callers are
        # already responsible for only ever passing a release_url that does
        # match this exact version.
        return ResolvedIdentity(
            "hacs",
            strip_version_prefix(latest_version),
            from_version,
            owner_repo=f"{owner}/{repo}",
            release_url=release_url,
        )

    if device_manufacturer is not None and device_model is not None:
        return ResolvedIdentity(
            "devices",
            strip_version_prefix(latest_version),
            from_version,
            manufacturer_model=f"{device_manufacturer}/{device_model}",
        )

    if app_slug is not None:
        return ResolvedIdentity("apps", strip_version_prefix(latest_version), from_version, app_slug=app_slug)

    return None
