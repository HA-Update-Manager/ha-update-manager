"""Version-size classification: given the versions an update jumps between,
how big a change is this -- small, medium, or big?

Kept free of any homeassistant import so it can be unit tested with plain
pytest -- see tests/test_semver.py and the same reasoning already applied to
previous-state-tracker's IgnoredStates helper.
"""
from __future__ import annotations

import re
from typing import Literal, NamedTuple

# Deliberately generic, not semver's own vocabulary (renamed 2026-07-16, see
# FUTURE.md): "small"/"medium"/"big" is a scale any version scheme's own
# classifier can map onto -- semver, HA Core's calendar versioning, and git
# commit hashes each have their own notion of "small" below, and a future
# scheme can add its own without needing new top-level categories. There's
# no separate "unknown" bucket: anything that can't be confidently placed
# (not strict semver, not HA Core's calendar shape, not a recognizable
# commit hash, a downgrade, or an identical/re-announced version) is "big",
# the same conservative-by-default treatment "unknown" used to get.
Size = Literal["small", "medium", "big"]

# Strict semver: exactly major.minor.patch, each a plain non-negative
# integer (no leading zeros other than "0" itself), with an optional
# pre-release (-foo.1) and/or build metadata (+build.5) suffix that we parse
# but deliberately ignore for size classification -- a pre-release of a new
# major is still "big", not something in between.
_SEMVER_RE = re.compile(
    r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)

# Calendar-style versioning, e.g. "2026.7.1" (year.month.patch) -- the
# scheme HA Core itself uses, but recognized purely by shape, not by which
# entity reports it: any other integration/device could use the same
# scheme too. This *also* matches _SEMVER_RE syntactically (three
# dot-separated integers), but doesn't carry semver's meaning: a January
# release the following year bumps the first number for calendar reasons
# alone, not because of a breaking change. Recognized as its own,
# deliberately excluded category rather than silently misclassified as
# "big".
_CALENDAR_VERSION_RE = re.compile(r"^20\d{2}\.(?:[1-9]|1[0-2])\.\d+$")

# A short (or full) git commit hash, e.g. HACS tracking a repo by commit
# instead of a release tag. Git's own abbreviation length isn't fixed at 7 --
# it auto-expands as needed to stay unique in a larger repo -- so this
# accepts a range (6 to a full 40-char SHA-1) rather than one exact length.
# Requires at least one a-f letter, not just digits: a plain numeric build
# counter (e.g. "123456") shouldn't be mistaken for a commit hash just
# because every digit happens to also be a valid hex character.
_GIT_COMMIT_RE = re.compile(r"^(?=.*[a-fA-F])[0-9a-fA-F]{6,40}$")


class ParsedVersion(NamedTuple):
    major: int
    minor: int
    patch: int


_V_PREFIX_RE = re.compile(r"^[vV](\d.*)$")


def strip_version_prefix(version: str) -> str:
    """Trims whitespace and a leading "v"/"V" immediately before a digit
    (e.g. "v1.2.3"), shared by every shape check/parser below so a version
    only ever needs to be normalized once, the same way regardless of which
    scheme it turns out to match. Only a v/V directly before a digit counts
    as a version-tag prefix, not e.g. a real version that happens to start
    with a word beginning in v (a "v"-then-non-digit fails every shape
    regex below either way, so this was always behaviorally equivalent for
    every call site here; made explicit so hacs_identity.py's own,
    previously-duplicated version of this same rule can reuse it directly
    instead of drifting out of sync)."""
    candidate = version.strip()
    match = _V_PREFIX_RE.match(candidate)
    return match.group(1) if match else candidate


def parse_semver(version: str) -> ParsedVersion | None:
    """Parse a strict semver core (major.minor.patch), ignoring any
    pre-release/build suffix. Returns None -- never a best-effort guess --
    for anything that isn't strict semver, including HA Core's own calendar
    versions (see is_calendar_version) and anything else that merely
    *looks* like it could be a version (2-part versions, non-numeric
    components, etc.)."""
    candidate = strip_version_prefix(version)
    if not _SEMVER_RE.match(candidate):
        return None
    core = candidate.split("-", 1)[0].split("+", 1)[0]
    major, minor, patch = (int(part) for part in core.split("."))
    return ParsedVersion(major, minor, patch)


def is_calendar_version(version: str) -> bool:
    """True for versions shaped like calendar-style YYYY.M.P versioning
    (e.g. "2026.7.1") -- the scheme HA Core itself uses, but this is a pure
    shape check, not specific to any one entity or integration. Checked
    independently of parse_semver: something can match this shape without
    also being valid strict semver (e.g. a leading zero in the month/patch
    part), and vice versa a plain "2026.7.1" is valid strict semver too --
    this function is what actually excludes it from being treated as one."""
    return bool(_CALENDAR_VERSION_RE.match(strip_version_prefix(version)))


def is_git_commit_version(version: str) -> bool:
    """True for something shaped like a git commit hash (e.g. HACS tracking
    a repo by commit rather than a release tag)."""
    return bool(_GIT_COMMIT_RE.match(version.strip()))


def _parse_calendar(version: str) -> ParsedVersion:
    """Parses a calendar-style version (year.month.patch) into the same
    shape parse_semver returns, so the jump-comparison logic below can be
    reused unchanged. Only meaningful once is_calendar_version has
    already confirmed the shape -- this doesn't re-validate it."""
    candidate = strip_version_prefix(version)
    year, month, patch = (int(part) for part in candidate.split("."))
    return ParsedVersion(year, month, patch)


def classify_version_size(previous: str, current: str) -> Size:
    """Classify how big a change the jump from `previous` to `current` is.

    HA Core's calendar versioning (year.month.patch) is handled on its own
    terms when *both* sides use it: the month is what "medium" means here
    (a new monthly feature release), the patch component is what "small"
    means (an in-month bugfix release) -- but never "big", on purpose. A
    year rollover (2026.12.x -> 2027.1.0) is just another month boundary in
    HA's own release cadence, not a signal of more risk than any other
    monthly release; treating the year digit as meaningful would repeat the
    exact misreading this special-casing exists to avoid.

    A git commit hash on *both* sides (e.g. HACS tracking a repo by commit)
    is "medium": there's no ordering signal at all (you can't tell which of
    two hashes came first without consulting git history itself), so it's
    deliberately not "small", but a recognized, deliberate tracking choice
    rather than truly unknown either.

    "big" (treated conservatively, i.e. as if it might be a breaking change)
    covers everything else: either side not strict semver, exactly one side
    (not both) using HA Core's calendar scheme or a commit hash, identical
    hashes (no real jump to classify), or `current` not actually newer than
    `previous` (e.g. a rollback or a re-announced identical version)."""
    prev_is_calendar = is_calendar_version(previous)
    curr_is_calendar = is_calendar_version(current)
    if prev_is_calendar and curr_is_calendar:
        prev = _parse_calendar(previous)
        curr = _parse_calendar(current)
        if curr <= prev:
            return "big"
        if curr.major != prev.major or curr.minor != prev.minor:
            return "medium"
        return "small"
    if prev_is_calendar or curr_is_calendar:
        return "big"

    prev_is_commit = is_git_commit_version(previous)
    curr_is_commit = is_git_commit_version(current)
    if prev_is_commit and curr_is_commit:
        return "big" if current == previous else "medium"
    if prev_is_commit or curr_is_commit:
        return "big"

    prev = parse_semver(previous)
    curr = parse_semver(current)
    if prev is None or curr is None:
        return "big"
    if curr <= prev:
        return "big"
    if curr.major != prev.major:
        return "big"
    if curr.minor != prev.minor:
        return "medium"
    return "small"
