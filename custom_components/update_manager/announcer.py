"""Pure logic for auto-install's "announce, don't just install" behaviour
(see FUTURE.md's "Auto-install (niveau 3): ontwerp"). No `homeassistant`
imports, following the same pure-logic-first pattern as semver.py/staging.py
-- independently testable, and importable via the same importlib trick the
existing tests use, bypassing pytest-homeassistant-custom-component.

An update reaching "ready" (staging.py) with auto-install enabled for its
size (small/medium/big, see semver.py) doesn't get installed immediately:
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


class AutoInstallRules(NamedTuple):
    small_auto_install: bool
    medium_auto_install: bool
    big_auto_install: bool
    announce_wait: timedelta


class AutoInstallContext(NamedTuple):
    """Why + when a specific auto-install dispatch happened, attributed all
    the way through to install_log.py's own history entry -- built once, in
    install_manager.py's own _async_execute (right before the install is
    actually dispatched, using effective_auto_install_state's own `reason`
    above), and threaded through rollout_manager.py's own queue for a
    Zigbee-paced install that doesn't actually dispatch until later."""

    to_version: str
    reason: str  # "rules" or "trusted_voter"
    trusted_voter_usernames: list[str]  # only non-empty for that reason
    announced_at: datetime | None  # None only if somehow executed with no announcement on record


def size_auto_install_enabled(size: Size, rules: AutoInstallRules) -> bool:
    return {
        "small": rules.small_auto_install,
        "medium": rules.medium_auto_install,
        "big": rules.big_auto_install,
    }[size]


def effective_auto_install_state(
    *, status: str, size_enabled: bool, auto_install_excluded: bool, trusted_vote: str | None
) -> tuple[bool, bool, str | None]:
    """(is_ready, auto_install_enabled, reason) after folding in a trusted
    voter's already-aggregated verdict for this exact pending version, if
    any (see community_verdict.py's own async_get_verdict for how a list of
    trusted usernames' individual votes becomes this single value -- this
    function only ever sees the result, never the raw list). Direct user
    feedback, 2026-07-23 ("installeer altijd automatisch als [klaptafel]
    een update als healthy heeft beoordeeld, ongeacht mijn eigen rules" ->
    confirmed symmetric while planning: a trusted "problematic" verdict
    blocks just as firmly).

    auto_install_excluded (Core/Supervisor/OS, plus anything the user
    explicitly excluded) is a hard, unconditional gate either way -- a
    trusted "healthy" vote never reaches past it, exactly like the size
    toggle never does today. So is an explicit user skip (status ==
    "skipped"): found by review, a bare trusted-healthy override that
    ignored status entirely would silently un-skip a version the user
    deliberately told Home Assistant to skip via update.skip, the moment
    someone they trust rated it healthy -- a direct, deliberate user action
    outranks an indirect trust setting, same reasoning as
    auto_install_excluded. `installable` isn't a parameter here at all:
    that's still install_manager.py's own separate, always-applies gate
    (announcer.py has never known about it, decide_action takes it as its
    own argument), unaffected by any of this.

    A trusted "healthy" vote overrides *both* the size-based toggle and the
    staging wait period (`is_ready`) for anything else -- the whole point of
    naming someone more trusted than your own rules is that their
    judgement can skip the wait, not just the toggle. A trusted
    "problematic" vote blocks eligibility outright, even when status is
    already "ready" and the size's own toggle is on: same reasoning, the
    other direction. Neither changes how decide_action itself sequences
    announce/execute -- only what feeds into it."""
    is_ready = status == "ready"
    if auto_install_excluded or status == "skipped":
        return is_ready, False, None
    if trusted_vote == "problematic":
        return is_ready, False, None
    if trusted_vote == "healthy":
        return True, True, "trusted_voter"
    return is_ready, size_enabled, ("rules" if size_enabled else None)


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
) -> AnnouncementAction:
    """What should happen right now to this entity's pending-install
    announcement?

    - "announce": start a new cancellable countdown.
    - "execute": the countdown elapsed uncancelled -- actually install now.
    - "remove": an announcement exists but no longer applies (rule turned
      off, update resolved itself/changed/disappeared, or the user
      cancelled this exact target version) -- clear it, no user action
      needed (see FUTURE.md: only a real cancel needs a manual dismiss).
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

    if existing is None:
        return "announce"

    if existing.to_version != current_to_version:
        # The pending update changed underneath the existing announcement
        # (e.g. a newer version appeared before the old one was installed)
        # -- clear it rather than firing on stale data; a fresh "announce"
        # follows once this same check runs again with existing=None.
        return "remove"

    if now >= existing.execute_at:
        return "execute"

    return "none"


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
