"""Patch/minor/major-aware staging: given a version-jump classification and
how long the update has been available, decide whether it's ready, still
waiting out its cooldown, or blocked pending a manual decision.

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
    from .semver import VersionJump

StagingStatus = Literal["ready", "waiting", "blocked"]


class StagingRules(NamedTuple):
    """Wait time before showing/installing is allowed, per jump type.
    Every jump type -- including major and unknown -- is independently
    configurable: a wait of None means "always blocked", never resolving to
    "ready" on its own no matter how long the update has existed, but that's
    a choice encoded in the rules passed in, not something this module
    enforces on anyone's behalf. Being conservative about major/unknown is
    the *default* (see DEFAULT_RULES below), not a built-in floor a user
    can't turn off -- same reasoning as Core/Supervisor/HAOS being a
    default-manual category in FUTURE.md rather than a hardcoded one, except
    here even that default is meant to be overridable."""

    patch_wait: timedelta | None
    minor_wait: timedelta | None
    major_wait: timedelta | None
    unknown_wait: timedelta | None


# A reasonable, conservative starting point; expected to become a
# user-configurable choice (the "Behoudend/Gebalanceerd/Vrij" presets from
# FUTURE.md) once there's a config/options flow for it, not a decision this
# module should hardcode an opinion about beyond providing *a* sensible
# default. major_wait/unknown_wait default to None (always blocked) but,
# unlike the previous design, a caller can set them to a real timedelta.
DEFAULT_RULES = StagingRules(
    patch_wait=timedelta(0),
    minor_wait=timedelta(days=7),
    major_wait=None,
    unknown_wait=None,
)


class StagingResult(NamedTuple):
    status: StagingStatus
    # Only meaningful when status == "waiting": how much longer until it
    # naturally becomes "ready" with no other input needed.
    remaining: timedelta | None


def evaluate_staging(
    jump: VersionJump,
    available_since: datetime,
    now: datetime,
    rules: StagingRules = DEFAULT_RULES,
) -> StagingResult:
    """`available_since` and `now` must both be timezone-aware (or both
    naive) datetimes in the same timezone -- callers are expected to pass
    HA's own dt_util.utcnow()-style values, this function doesn't normalize
    timezones itself."""
    wait = {
        "patch": rules.patch_wait,
        "minor": rules.minor_wait,
        "major": rules.major_wait,
        "unknown": rules.unknown_wait,
    }[jump]

    if wait is None:
        return StagingResult("blocked", None)

    elapsed = now - available_since
    if elapsed >= wait:
        return StagingResult("ready", None)
    return StagingResult("waiting", wait - elapsed)
