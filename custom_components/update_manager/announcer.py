"""Pure logic for auto-install's "announce, don't just install" behaviour.
No `homeassistant` imports, following the same pure-logic-first pattern as
semver.py/staging.py
-- independently testable, and importable via the same importlib trick the
existing tests use, bypassing pytest-homeassistant-custom-component.

An update reaching "ready" (staging.py) with auto-install enabled for its
size (small/medium/large, see semver.py) doesn't get installed immediately:
it's announced first, with a fixed, cancellable wait before
install_manager.py actually calls `update.install`. This module only
decides *what should happen right now* for one entity; it owns no state
and does no I/O itself.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal, NamedTuple

if TYPE_CHECKING:
    # Only used in a type annotation; guarded so this module (like
    # staging.py/semver.py) can be loaded standalone via importlib for plain-
    # pytest testing, without needing package-relative imports to resolve.
    from .semver import Size

AnnouncementAction = Literal["none", "announce", "execute", "remove"]
AutoInstallReason = Literal["rules", "trusted_voter", "whitelist"]


class AutoInstallRules(NamedTuple):
    small_auto_install: bool
    medium_auto_install: bool
    large_auto_install: bool
    announce_wait: timedelta


class AutoInstallContext(NamedTuple):
    """Why + when a specific auto-install dispatch happened, attributed all
    the way through to install_log.py's own history entry -- built once, in
    install_manager.py's own _async_execute (right before the install is
    actually dispatched, using effective_auto_install_state's own `reason`
    above), and threaded through rollout_manager.py's own queue for a
    Zigbee-paced install that doesn't actually dispatch until later."""

    to_version: str
    reason: AutoInstallReason
    trusted_voter_usernames: list[str]  # only non-empty for that reason
    announced_at: datetime | None  # None only if somehow executed with no announcement on record


def size_auto_install_enabled(size: Size, rules: AutoInstallRules) -> bool:
    return {
        "small": rules.small_auto_install,
        "medium": rules.medium_auto_install,
        "large": rules.large_auto_install,
    }[size]


def effective_auto_install_state(
    *,
    status: str,
    size_enabled: bool,
    auto_install_excluded: bool,
    trusted_vote: str | None,
    community_problematic_count: int = 0,
    auto_install_whitelisted: bool = False,
) -> tuple[bool, bool, AutoInstallReason | None]:
    """(is_ready, auto_install_enabled, reason) after folding in (a)
    auto_install_whitelisted, the standing "always auto-update" override
    (see CONF_WHITELISTED_ENTITIES's own comment), (b) a trusted voter's
    already-aggregated verdict for this exact pending version, if any (see
    community_verdict.py's own async_get_verdict for how a list of trusted
    usernames' individual votes becomes this single value -- this function
    only ever sees the result, never the raw list), and (c) the wider
    crowd's own raw problematic count. Direct user feedback, 2026-07-23
    ("installeer altijd automatisch als [klaptafel] een update als healthy
    heeft beoordeeld, ongeacht mijn eigen rules" -> confirmed symmetric
    while planning: a trusted "problematic" verdict blocks just as firmly).

    auto_install_excluded (Core/Supervisor/OS, plus anything the user
    explicitly excluded) is a hard, unconditional gate either way -- a
    trusted "healthy" vote (or the whitelist override below) never reaches
    past it, exactly like the size toggle never does today. So is an
    explicit user skip (status == "skipped"): found by review, a bare
    trusted-healthy override that ignored status entirely would silently
    un-skip a version the user deliberately told Home Assistant to skip via
    update.skip, the moment someone they trust rated it healthy -- a
    direct, deliberate user action outranks an indirect trust setting, same
    reasoning as auto_install_excluded. An entity can never be both
    excluded and whitelisted at once (see CONF_WHITELISTED_ENTITIES's own
    comment), so there's no ordering question between those two to resolve
    here -- only ever one or the other, or neither. `installable` isn't a
    parameter here at all: that's still install_manager.py's own separate,
    always-applies gate (announcer.py has never known about it,
    decide_action takes it as its own argument), unaffected by any of this.

    auto_install_whitelisted is checked next, before the trusted-vote logic
    below: direct user feedback, 2026-10-10, confirming it should outrank a
    trusted voter's own judgement too, not just the size toggle and the
    wait -- it's a standing, deliberately configured override for this
    exact entity, a stronger signal than a vote about a version. Forces
    both is_ready and auto_install_enabled True unconditionally, skipping
    size_enabled/trusted_vote/community_problematic_count entirely: the
    whole point (see issue #10) is installing the instant something is
    available, not merely winning the size toggle the way a trusted-healthy
    vote does.

    A trusted "healthy" vote overrides *both* the size-based toggle and the
    staging wait period (`is_ready`) for anything else -- the whole point of
    naming someone more trusted than your own rules is that their
    judgement can skip the wait, not just the toggle -- and it wins even
    when community_problematic_count is nonzero: direct user feedback,
    2026-07-29, when asked whether a stray untrusted problematic report
    should override a trusted healthy vote -- a trusted voter's own
    judgment should count for something, otherwise trusting them at all is
    pointless. So this check comes first, unconditionally.

    Only once there's no trusted-healthy override in play does
    community_problematic_count matter: any problematic vote at all, from
    anyone, however small a minority, blocks eligibility outright -- no
    quorum, no percentage, the same asymmetric-safety reasoning already
    applied elsewhere (quorum only ever mattered for trusting the crowd
    enough to force an install, a feature that doesn't exist yet; blocking
    needs no quorum, since erring towards caution is always the safe
    direction). This subsumes the old,
    narrower "a trusted voter's own problematic vote blocks" rule: a
    trusted voter's problematic vote is itself already counted inside the
    aggregate community_problematic_count, so that case no longer needs its
    own separate branch. Neither this nor the trusted-healthy override
    changes how decide_action itself sequences announce/execute -- only
    what feeds into it (whitelist is the one exception, see
    decide_action's own `instant` parameter)."""
    is_ready = status == "ready"
    if auto_install_excluded or status == "skipped":
        return is_ready, False, None
    if auto_install_whitelisted:
        return True, True, "whitelist"
    if trusted_vote == "healthy":
        return True, True, "trusted_voter"
    if community_problematic_count > 0:
        return is_ready, False, None
    return is_ready, size_enabled, ("rules" if size_enabled else None)


def needs_manual_action(
    *,
    status: str,
    version_size: Size,
    auto_install_excluded: bool,
    trusted_vote: str | None,
    community_problematic_count: int,
    rules: AutoInstallRules,
    master_enabled: bool,
    auto_install_whitelisted: bool = False,
) -> bool:
    """True for a "ready" update that won't be auto-installed -- the exact
    set install_manager.py's own periodic tick otherwise leaves for a
    manual Install click. sensor.py's own UpdateManagerNeedsManualAction
    sensor is this function's only caller, direct user feedback, 2026-08-15:
    "Ready to update" already exists but mixes in everything auto-install is
    about to handle on its own, undercutting its value as "how much do I
    actually need to do myself right now."

    Reuses effective_auto_install_state's own eligibility logic above, not
    decide_action further down (that one additionally sequences announce/
    execute timing, irrelevant to this plain yes/no question) -- plus the
    master pause switch, decide_action's own separate gate: nothing
    auto-installs at all while paused, regardless of what the rules say, so
    every "ready" update counts as needing manual action then too.
    installable isn't a parameter here, same as effective_auto_install_state
    itself -- callers are expected to already be iterating an
    installable-only set (e.g. update_status.py's own "ready" bucket, which
    already excludes not-installable updates before this ever runs)."""
    if status != "ready":
        return False
    size_enabled = size_auto_install_enabled(version_size, rules)
    _is_ready, auto_install_enabled, _reason = effective_auto_install_state(
        status=status,
        size_enabled=size_enabled,
        auto_install_excluded=auto_install_excluded,
        trusted_vote=trusted_vote,
        community_problematic_count=community_problematic_count,
        auto_install_whitelisted=auto_install_whitelisted,
    )
    return not (auto_install_enabled and master_enabled)


class PendingAnnouncement(NamedTuple):
    entity_id: str
    to_version: str
    announced_at: datetime
    execute_at: datetime


def decide_action(
    *,
    is_ready: bool,
    auto_install_enabled: bool,
    master_enabled: bool,
    installable: bool,
    existing: PendingAnnouncement | None,
    cancelled_to_version: str | None,
    current_to_version: str,
    now: datetime,
    announce_wait: timedelta,
    instant: bool = False,
) -> AnnouncementAction:
    """What should happen right now to this entity's pending-install
    announcement?

    - "announce": start a new cancellable countdown.
    - "execute": the countdown elapsed uncancelled -- actually install now.
    - "remove": an announcement exists but no longer applies (rule turned
      off, update resolved itself/changed/disappeared, or the user
      cancelled this exact target version) -- clear it, no user action
      needed, only a real cancel needs a manual dismiss.
    - "none": nothing to do.

    Deliberately sequential, not overlapping: the announcement only starts
    once staging.py's own status is actually "ready" (is_ready=True), never
    earlier. An overlapping design (start announcing once the remaining
    uitsteltermijn drops to announce_wait, before status flips to "ready")
    was tried and reverted (2026-07-17, direct user feedback): a "waiting"
    entity that already had an active cancel countdown running underneath
    it read as self-contradictory in the UI, and wasn't explainable to
    users in one sentence. Total time from "available" to "installed" is
    now plainly uitsteltermijn + aankondigingstermijn, matching what a user
    reading those two settings would expect.

    `instant` (True only for a whitelisted entity, see
    effective_auto_install_state's own `auto_install_whitelisted`) is the
    one deliberate exception to the normal announce-then-wait sequencing:
    skips straight to "execute" once ready/enabled/installable and not
    explicitly cancelled, with no announcement to begin with -- the entire
    point of naming an entity "always auto-update" is installing it the
    instant it's available, not a shorter wait. Checked after the
    cancellation check above, and only once `existing is None`: a direct
    cancel_scheduled_install call for this exact version still outranks the
    standing whitelist override (same "direct action beats indirect
    setting" precedent as auto_install_excluded elsewhere in this module),
    and `existing` (see below) takes priority whenever install_manager.py's
    own backoff after a hard failure already put a record there -- a
    whitelisted entity backs off exactly like a normal one once it's
    actually failed once, it just never announces *before* a first attempt.

    master_enabled (the global pause switch, const.py's CONF_ENABLED) is
    deliberately its own parameter, not folded into auto_install_enabled --
    while paused, an existing announcement is frozen in place (this
    function returns "none", touching nothing at all) rather than removed,
    so resuming continues the *same* countdown from the *same* execute_at
    instead of restarting a fresh announce_wait from whenever the switch
    happened to flip back on. Direct user feedback (2026-07-17), after
    seeing an in-flight countdown jump forward by a full announce_wait the
    moment the pause switch was toggled off and back on. auto_install_enabled
    turning off for a real reason (the size's own rule, exclusion, or the
    entity losing INSTALL support) still removes the announcement as before
    -- that is a genuine, lasting change in disposition, not a pause.
    """
    if not master_enabled:
        return "none"

    if not is_ready or not auto_install_enabled or not installable:
        return "remove" if existing is not None else "none"

    if cancelled_to_version is not None and cancelled_to_version == current_to_version:
        # The user explicitly cancelled *this* target version -- stays
        # quiet unless/until a newer version appears (a different
        # to_version no longer matches the cancelled one).
        return "remove" if existing is not None else "none"

    # existing (a real PendingAnnouncement) governs regardless of instant
    # once one exists -- install_manager.py's own backoff after a hard
    # failure writes one here even for an otherwise-instant entity (see
    # handle_install_failure), reusing this exact same mechanism instead of
    # a second, parallel notion of "scheduled" the rest of this module (and
    # every caller/consumer of PendingAnnouncement) would need to know
    # about too. Checked before instant below, not after: this is what
    # lets a failed whitelisted entity's retry respect its own backoff
    # instead of instant-executing again on the very next tick.
    if existing is not None:
        if existing.to_version != current_to_version:
            # The pending update changed underneath the existing
            # announcement (e.g. a newer version appeared before the old
            # one was installed) -- clear it rather than firing on stale
            # data; a fresh "announce"/instant-"execute" follows once this
            # same check runs again with existing=None.
            return "remove"
        return "execute" if now >= existing.execute_at else "none"

    if instant:
        return "execute"

    return "announce"


def start_announcement(
    entity_id: str,
    to_version: str,
    now: datetime,
    announce_wait: timedelta,
) -> PendingAnnouncement:
    """Only ever called once is_ready (see decide_action) -- the countdown
    always runs the full announce_wait from right now, not anchored to
    anything about the uitsteltermijn (which has already finished by this
    point)."""
    return PendingAnnouncement(
        entity_id=entity_id,
        to_version=to_version,
        announced_at=now,
        execute_at=now + announce_wait,
    )
