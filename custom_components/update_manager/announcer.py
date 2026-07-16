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


def size_auto_install_enabled(size: Size, rules: AutoInstallRules) -> bool:
    return {
        "small": rules.small_auto_install,
        "medium": rules.medium_auto_install,
        "big": rules.big_auto_install,
    }[size]


class PendingAnnouncement(NamedTuple):
    entity_id: str
    to_version: str
    announced_at: datetime
    execute_at: datetime


def decide_action(
    *,
    is_ready: bool,
    remaining: timedelta | None,
    auto_install_enabled: bool,
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

    `remaining` is staging.py's own "how much longer until ready" right now
    (None once ready, or while blocked with no configured wait). Announcing
    starts as soon as that gets down to announce_wait, not only once fully
    ready -- so the cancel window lands *inside* the tail end of the
    uitsteltermijn instead of being tacked on after it finishes. Found via
    direct user feedback: with the old "only announce once fully ready"
    rule, the total time from "available" to "installed" quietly became
    uitsteltermijn + aankondigingstermijn, longer than the uitsteltermijn
    setting implies, and the traffic light stayed green (implying "safe to
    install yourself right now") for that whole extra stretch -- a manual
    install and the automatic one could both fire around the same time.
    """
    ready_enough = is_ready or (remaining is not None and remaining <= announce_wait)
    if not ready_enough or not auto_install_enabled or not installable:
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
    remaining: timedelta | None = None,
) -> PendingAnnouncement:
    """`remaining` (staging.py's "how much longer until ready" at the
    moment of announcing, None if already fully ready) anchors execute_at to
    when the uitsteltermijn itself completes, not always now + announce_wait
    -- the announcement effectively starts announce_wait early. If
    announce_wait is longer than what's actually left (a short/zero
    uitsteltermijn), the full announce_wait wins instead: never less
    cancel-time than configured, see decide_action."""
    natural_ready_at = now + remaining if remaining is not None else now
    return PendingAnnouncement(
        entity_id=entity_id,
        to_version=to_version,
        announced_at=now,
        execute_at=max(natural_ready_at, now + announce_wait),
    )
