"""Size-aware staging: given a version-size classification (small/medium/
big, see semver.py) and how long the update has been available, decide
whether it's ready, still waiting out its cooldown, or blocked pending a
manual decision.

Kept free of any homeassistant import, same reasoning as semver.py -- see
tests/test_staging.py.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal, NamedTuple

if TYPE_CHECKING:
    # Only used in a type annotation; guarded so this module (like semver.py)
    # can be loaded standalone via importlib for plain-pytest testing,
    # without needing package-relative imports to resolve.
    from .semver import Size

StagingStatus = Literal["ready", "waiting", "blocked"]


class StagingRules(NamedTuple):
    """Wait time before showing/installing is allowed, per size. Every
    size -- including "big" -- is independently configurable: a wait of
    None means "always blocked", never resolving to "ready" on its own no
    matter how long the update has existed, but that's a choice encoded in
    the rules passed in, not something this module enforces on anyone's
    behalf. Being conservative about "big" is the *default* (see
    DEFAULT_RULES below), not a built-in floor a user can't turn off --
    same reasoning as Core/Supervisor/HAOS being a hard, non-configurable
    exception in FUTURE.md, except here even the default is meant to be
    overridable."""

    small_wait: timedelta | None
    medium_wait: timedelta | None
    big_wait: timedelta | None


# A reasonable, conservative starting point; expected to become a
# user-configurable choice (the "Behoudend/Gebalanceerd/Vrij" presets from
# FUTURE.md) once there's a config/options flow for it, not a decision this
# module should hardcode an opinion about beyond providing *a* sensible
# default. big_wait defaults to None (always blocked) but, unlike the
# previous design, a caller can set it to a real timedelta.
DEFAULT_RULES = StagingRules(
    small_wait=timedelta(0),
    medium_wait=timedelta(days=7),
    big_wait=None,
)


class StagingResult(NamedTuple):
    status: StagingStatus
    # Only meaningful when status == "waiting": how much longer until it
    # naturally becomes "ready" with no other input needed.
    remaining: timedelta | None


def wait_for_size(rules: StagingRules, size: Size) -> timedelta | None:
    """The one place that maps a size to its field on StagingRules --
    coordinator.py needs this same lookup for its own recorder-query
    shortcut, so it imports this instead of re-deriving it."""
    return {
        "small": rules.small_wait,
        "medium": rules.medium_wait,
        "big": rules.big_wait,
    }[size]


def evaluate_staging(
    size: Size,
    available_since: datetime,
    now: datetime,
    rules: StagingRules = DEFAULT_RULES,
) -> StagingResult:
    """`available_since` and `now` must both be timezone-aware (or both
    naive) datetimes in the same timezone -- callers are expected to pass
    HA's own dt_util.utcnow()-style values, this function doesn't normalize
    timezones itself."""
    wait = wait_for_size(rules, size)

    if wait is None:
        return StagingResult("blocked", None)

    elapsed = now - available_since
    if elapsed >= wait:
        return StagingResult("ready", None)
    return StagingResult("waiting", wait - elapsed)
