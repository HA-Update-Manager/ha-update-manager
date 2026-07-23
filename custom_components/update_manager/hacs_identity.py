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
# votes/home-assistant/<core|supervisor|os>/... structure (see FUTURE.md).
# These three entity_ids are HA core's own fixed, well-known ones (confirmed
# against real bug reports/service-call examples referencing them, not
# guessed).
_HOME_ASSISTANT_COMPONENT_BY_ENTITY_ID = {
    "update.home_assistant_core_update": "core",
    "update.home_assistant_supervisor_update": "supervisor",
    "update.home_assistant_operating_system_update": "os",
}


class ResolvedIdentity(NamedTuple):
    """Everything both the read side (community_verdict.py, needs only
    .votes_path) and the write side (community_vote.py, needs the individual
    fields to build a vote's issue body) need, computed once instead of
    twice. Exactly one of component/owner_repo/manufacturer_model/app_slug
    is set, matching which category this identity is. manufacturer_model is
    already the joined "manufacturer/model" string (found by review: every
    consumer -- votes_path below, vote_issue_body.py's own "Manufacturer/
    model" field -- immediately joined the two, keeping them as separate
    fields just duplicated that join)."""

    category: str
    version: str
    component: str | None = None
    owner_repo: str | None = None
    manufacturer_model: str | None = None
    app_slug: str | None = None

    @property
    def votes_path(self) -> str:
        if self.category == "home-assistant":
            return f"home-assistant/{self.component}/{self.version}"
        if self.category == "hacs":
            return f"hacs/{self.owner_repo}/{self.version}"
        if self.category == "devices":
            return f"devices/{self.manufacturer_model}/{self.version}"
        return f"apps/{self.app_slug}/{self.version}"


def resolve_identity(
    entity_id: str,
    release_url: str | None,
    latest_version: str,
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
    component = _HOME_ASSISTANT_COMPONENT_BY_ENTITY_ID.get(entity_id)
    if component is not None:
        return ResolvedIdentity("home-assistant", strip_version_prefix(latest_version), component=component)

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
        # owner/repo, never the version.
        return ResolvedIdentity("hacs", strip_version_prefix(latest_version), owner_repo=f"{owner}/{repo}")

    if device_manufacturer is not None and device_model is not None:
        return ResolvedIdentity(
            "devices",
            strip_version_prefix(latest_version),
            manufacturer_model=f"{device_manufacturer}/{device_model}",
        )

    if app_slug is not None:
        return ResolvedIdentity("apps", strip_version_prefix(latest_version), app_slug=app_slug)

    return None
