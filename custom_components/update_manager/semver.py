"""Semver-aware version-jump classification.

Kept free of any homeassistant import so it can be unit tested with plain
pytest -- see tests/test_semver.py and the same reasoning already applied to
previous-state-tracker's IgnoredStates helper.
"""
from __future__ import annotations

import re
from typing import Literal, NamedTuple

VersionJump = Literal["patch", "minor", "major", "unknown"]

# Strict semver: exactly major.minor.patch, each a plain non-negative
# integer (no leading zeros other than "0" itself), with an optional
# pre-release (-foo.1) and/or build metadata (+build.5) suffix that we parse
# but deliberately ignore for jump classification -- a pre-release of a new
# major is still "major", not something in between.
_SEMVER_RE = re.compile(
    r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)

# HA Core's own calendar versioning, e.g. "2026.7.1" (year.month.patch).
# This *also* matches _SEMVER_RE syntactically (three dot-separated
# integers), but doesn't carry semver's meaning: a January release the
# following year bumps the first number for calendar reasons alone, not
# because of a breaking change. Recognized as its own, deliberately
# excluded category rather than silently misclassified as "major".
_HA_CORE_CALENDAR_RE = re.compile(r"^20\d{2}\.(?:[1-9]|1[0-2])\.\d+$")


class ParsedVersion(NamedTuple):
    major: int
    minor: int
    patch: int


def parse_semver(version: str) -> ParsedVersion | None:
    """Parse a strict semver core (major.minor.patch), ignoring any
    pre-release/build suffix. Returns None -- never a best-effort guess --
    for anything that isn't strict semver, including HA Core's own calendar
    versions (see is_ha_core_calendar_version) and anything else that merely
    *looks* like it could be a version (2-part versions, non-numeric
    components, etc.)."""
    candidate = version.strip()
    if candidate.startswith(("v", "V")):
        candidate = candidate[1:]
    if not _SEMVER_RE.match(candidate):
        return None
    core = candidate.split("-", 1)[0].split("+", 1)[0]
    major, minor, patch = (int(part) for part in core.split("."))
    return ParsedVersion(major, minor, patch)


def is_ha_core_calendar_version(version: str) -> bool:
    """True for versions shaped like Home Assistant Core's own YYYY.M.P
    calendar versioning (e.g. "2026.7.1"). Checked independently of
    parse_semver: something can match this shape without also being valid
    strict semver (e.g. a leading zero in the month/patch part), and vice
    versa a plain "2026.7.1" is valid strict semver too -- this function is
    what actually excludes it from being treated as one."""
    candidate = version.strip()
    if candidate.startswith(("v", "V")):
        candidate = candidate[1:]
    return bool(_HA_CORE_CALENDAR_RE.match(candidate))


def classify_version_jump(previous: str, current: str) -> VersionJump:
    """Classify the jump from `previous` to `current`.

    "unknown" (treated conservatively, i.e. as if it might be a major/
    breaking change) covers: either side not strict semver, either side an
    HA Core-style calendar version, or `current` not actually newer than
    `previous` (no jump to classify, e.g. a rollback or a re-announced
    identical version)."""
    if is_ha_core_calendar_version(previous) or is_ha_core_calendar_version(current):
        return "unknown"

    prev = parse_semver(previous)
    curr = parse_semver(current)
    if prev is None or curr is None:
        return "unknown"

    if curr <= prev:
        return "unknown"
    if curr.major != prev.major:
        return "major"
    if curr.minor != prev.minor:
        return "minor"
    return "patch"
