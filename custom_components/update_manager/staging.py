"""Patch/minor/major-aware staging: given a version-jump classification and
how long the update has been available, decide whether it's ready, still
waiting out its cooldown, or permanently blocked pending a manual decision.

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
    major/unknown have no wait concept -- they're always "blocked" instead,
    requiring a conscious manual decision, never just a matter of time."""

    patch_wait: timedelta
    minor_wait: timedelta


# A reasonable starting default; expected to become a user-configurable
# choice (the "Behoudend/Gebalanceerd/Vrij" presets from FUTURE.md) once
# there's a config/options flow for it, not a decision this module should
# hardcode an opinion about beyond providing *a* sensible default.
DEFAULT_RULES = StagingRules(patch_wait=timedelta(0), minor_wait=timedelta(days=7))


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
    if jump in ("major", "unknown"):
        return StagingResult("blocked", None)

    wait = rules.patch_wait if jump == "patch" else rules.minor_wait
    elapsed = now - available_since
    if elapsed >= wait:
        return StagingResult("ready", None)
    return StagingResult("waiting", wait - elapsed)
