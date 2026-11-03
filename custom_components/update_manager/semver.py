"""Version-size classification: given the versions an update jumps between,
how large a change is this -- small, medium, or large?

Kept free of any homeassistant import so it can be unit tested with plain
pytest -- see tests/test_semver.py and the same reasoning already applied to
previous-state-tracker's IgnoredStates helper.
"""
from __future__ import annotations

import re
from typing import Literal, NamedTuple

# Deliberately generic, not semver's own vocabulary (renamed 2026-07-16):
# "small"/"medium"/"large" is a scale any version scheme's own
# classifier can map onto -- semver, HA Core's calendar versioning, and git
# commit hashes each have their own notion of "small" below, and a future
# scheme can add its own without needing new top-level categories. There's
# no separate "unknown" bucket: anything that can't be confidently placed
# (not strict semver, not HA Core's calendar shape, not a recognizable
# commit hash, a downgrade, or an identical/re-announced version) is "large"
# (renamed from "big" 2026-08-07, direct user feedback: "large" reads as a
# plain size next to small/medium, where "big" read more like a judgment
# call), the same conservative-by-default treatment "unknown" used to get.
Size = Literal["small", "medium", "large"]

# Strict semver: exactly major.minor.patch, each a plain non-negative
# integer (no leading zeros other than "0" itself), with an optional
# pre-release (-foo.1) and/or build metadata (+build.5) suffix that we parse
# but deliberately ignore for size classification -- a pre-release of a new
# major is still "large", not something in between.
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
# "large". Month accepts a zero-padded form ("07") as well as bare ("7") --
# found live, 2026-07-27: "2026.07.3" -> "2026.07.4" fell through this *and*
# strict semver's own leading-zero rejection, landing on the conservative
# "large" default despite being an ordinary same-month patch bump.
_CALENDAR_VERSION_RE = re.compile(r"^20\d{2}\.(?:0[1-9]|[1-9]|1[0-2])\.\d+$")

# A short (or full) git commit hash, e.g. HACS tracking a repo by commit
# instead of a release tag. Git's own abbreviation length isn't fixed at 7 --
# it auto-expands as needed to stay unique in a larger repo -- so this
# accepts a range (6 to a full 40-char SHA-1) rather than one exact length.
# Requires at least one a-f letter, not just digits: a plain numeric build
# counter (e.g. "123456") shouldn't be mistaken for a commit hash just
# because every digit happens to also be a valid hex character.
_GIT_COMMIT_RE = re.compile(r"^(?=.*[a-fA-F])[0-9a-fA-F]{6,40}$")

# Exactly major.minor -- no patch component at all (e.g. "18.0", "18.1").
# Distinct from strict semver (which requires all three) and from calendar
# versioning (which requires a year-shaped first component): some
# integrations/devices genuinely only ever report two numbers, with no
# separate patch tier to be "small" against. Found live, 2026-07-25: this
# used to silently fall through to "large" (the same conservative default any
# genuinely unrecognized shape gets), even for as small a jump as 18.0 ->
# 18.1.
_SHORT_SEMVER_RE = re.compile(
    r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)

# Exactly major.minor.patch.hotfix, a fourth, non-standard component some
# projects add for an in-place hotfix of an already-tagged patch release,
# found live 2026-11-02: v0.5.8 -> v0.5.9.1 was classified "large" (neither
# strict semver, which requires exactly three components, nor short semver,
# which requires exactly two, matched it) despite being an ordinary patch
# bump. Distinct from a build-metadata suffix (which strict semver already
# parses and ignores, see _SEMVER_RE): this is a genuine fourth numeric
# tier, not metadata.
_EXTENDED_SEMVER_RE = re.compile(
    r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


class ParsedVersion(NamedTuple):
    major: int
    minor: int
    patch: int
    # Only ever non-zero for an extended, four-component semver version
    # (is_extended_semver_version, e.g. the "1" in "0.5.9.1"). Defaults to
    # 0 so every other parser here keeps constructing a plain 3-arg
    # ParsedVersion unchanged, and still compares/orders exactly like a
    # plain 3-tuple did before this field existed.
    hotfix: int = 0


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
    candidate = str(version).strip()
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
    return bool(_GIT_COMMIT_RE.match(str(version).strip()))


def is_short_semver_version(version: str) -> bool:
    """True for a two-component major.minor version (no patch at all), e.g.
    "18.1" -- checked independently of parse_semver/is_calendar_version,
    same reasoning as those: a pure shape check, not tied to any one
    entity/integration. A version that also happens to be valid strict
    semver (three parts) never matches this too -- the trailing "$" anchor
    means a third dot-separated component (even a valid one) fails the
    match here, so there's no ambiguity between the two shapes."""
    return bool(_SHORT_SEMVER_RE.match(strip_version_prefix(version)))


def is_extended_semver_version(version: str) -> bool:
    """True for a four-component major.minor.patch.hotfix version, e.g.
    "0.5.9.1", checked independently of parse_semver, same reasoning as
    is_short_semver_version above. The trailing "$" anchor means a version
    with only three components (plain strict semver) never matches this
    too, same non-ambiguity between the two shapes."""
    return bool(_EXTENDED_SEMVER_RE.match(strip_version_prefix(version)))


def _parse_calendar(version: str) -> ParsedVersion:
    """Parses a calendar-style version (year.month.patch) into the same
    shape parse_semver returns, so the jump-comparison logic below can be
    reused unchanged. Only meaningful once is_calendar_version has
    already confirmed the shape -- this doesn't re-validate it."""
    candidate = strip_version_prefix(version)
    year, month, patch = (int(part) for part in candidate.split("."))
    return ParsedVersion(year, month, patch)


def _parse_short_semver(version: str) -> ParsedVersion:
    """Parses a two-component major.minor version into the same shape
    parse_semver returns, patch fixed at 0 (there's no third component to
    read) so the jump-comparison logic below can be reused unchanged. Only
    meaningful once is_short_semver_version has already confirmed the
    shape -- this doesn't re-validate it."""
    candidate = strip_version_prefix(version)
    core = candidate.split("-", 1)[0].split("+", 1)[0]
    major, minor = (int(part) for part in core.split("."))
    return ParsedVersion(major, minor, 0)


def _parse_semver_or_short(version: str) -> ParsedVersion | None:
    """Strict semver if it matches that shape, else the two-component short
    form (patch implicitly 0), else None -- one shared parse used for every
    non-calendar, non-commit-hash jump in classify_version_size below, so a
    *mixed* pair (one side full semver, the other missing just the patch,
    e.g. "0.36.2" -> "0.37") gets compared the same major/minor/patch way a
    same-shape pair would, instead of needing its own special case. Found
    live, 2026-07-27: this exact mixed case used to fall through both the
    "both short" and "both full" branches entirely (neither "both" condition
    was true) straight to the conservative "large" default, even though the
    minor component's own change (36 -> 37) was perfectly ordinary and
    detectable once the short side's missing patch is just treated as 0."""
    parsed = parse_semver(version)
    if parsed is not None:
        return parsed
    return _parse_short_semver(version) if is_short_semver_version(version) else None


def _parse_major_minor_patch_hotfix(version: str) -> ParsedVersion | None:
    """(major, minor, patch, hotfix) for short semver/strict semver (via
    _parse_semver_or_short above, hotfix implicitly 0 same as ParsedVersion's
    own default) or extended semver (is_extended_semver_version, the real
    fourth component), as one shared ParsedVersion so classify_version_size's
    own comparison below never needs to know how many trailing components
    either side actually had, the same "a missing component defaults to 0"
    reasoning _parse_semver_or_short already applies between short and
    strict semver. None for anything matching none of these three shapes."""
    normal = _parse_semver_or_short(version)
    if normal is not None:
        return normal
    if not is_extended_semver_version(version):
        return None
    candidate = strip_version_prefix(version)
    core = candidate.split("-", 1)[0].split("+", 1)[0]
    major, minor, patch, hotfix = (int(part) for part in core.split("."))
    return ParsedVersion(major, minor, patch, hotfix)


def classify_version_size(previous: str, current: str) -> Size:
    """Classify how big a change the jump from `previous` to `current` is.

    HA Core's calendar versioning (year.month.patch) is handled on its own
    terms when *both* sides use it: the month is what "medium" means here
    (a new monthly feature release), the patch component is what "small"
    means (an in-month bugfix release) -- but never "large", on purpose. A
    year rollover (2026.12.x -> 2027.1.0) is just another month boundary in
    HA's own release cadence, not a signal of more risk than any other
    monthly release; treating the year digit as meaningful would repeat the
    exact misreading this special-casing exists to avoid.

    A git commit hash on *both* sides (e.g. HACS tracking a repo by commit)
    is "medium": there's no ordering signal at all (you can't tell which of
    two hashes came first without consulting git history itself), so it's
    deliberately not "small", but a recognized, deliberate tracking choice
    rather than truly unknown either.

    A two-component major.minor version (no patch at all, e.g. "18.0" ->
    "18.1") is handled on the same terms as full semver (see
    _parse_semver_or_short): its missing patch is treated as 0, so "medium"
    still means the minor component changed, same reasoning as the
    git-commit-hash case for why this isn't left as unrecognized/"large" --
    a real, ordered jump between two recognized versions is a
    deliberately-tracked scheme. This also covers a *mixed* pair, one side
    full semver and the other short (e.g. "0.36.2" -> "0.37") the same way,
    found live 2026-07-27: this used to fall through to "large" for not being
    strict three-part semver *and* not being short on both sides at once.

    A fourth, non-standard hotfix component (is_extended_semver_version,
    e.g. "0.5.9.1") is handled the same way again: major/minor changing is
    still "large"/"medium" exactly as above, but a change confined to the
    patch *or* this fourth component (with major/minor unchanged) is
    "small" either way, the same "any change below minor is small"
    reasoning the plain three-part case already applies to its own patch
    component. Found live 2026-11-02: "0.5.8" -> "0.5.9.1" fell through to
    "large" before this, for matching neither strict semver (exactly three
    components) nor short semver (exactly two).

    "large" (treated conservatively, i.e. as if it might be a breaking change)
    covers everything else: either side not recognized as semver or short
    semver at all, exactly one side (not both) using HA Core's calendar
    scheme or a commit hash, identical hashes/versions (no real jump to
    classify), or `current` not actually newer than `previous` (e.g. a
    rollback or a re-announced identical version)."""
    previous = str(previous)
    current = str(current)
    prev_is_calendar = is_calendar_version(previous)
    curr_is_calendar = is_calendar_version(current)
    if prev_is_calendar and curr_is_calendar:
        prev = _parse_calendar(previous)
        curr = _parse_calendar(current)
        if curr <= prev:
            return "large"
        if curr.major != prev.major or curr.minor != prev.minor:
            return "medium"
        return "small"
    if prev_is_calendar or curr_is_calendar:
        return "large"

    prev_is_commit = is_git_commit_version(previous)
    curr_is_commit = is_git_commit_version(current)
    if prev_is_commit and curr_is_commit:
        return "large" if current == previous else "medium"
    if prev_is_commit or curr_is_commit:
        return "large"

    prev = _parse_major_minor_patch_hotfix(previous)
    curr = _parse_major_minor_patch_hotfix(current)
    if prev is None or curr is None:
        return "large"
    if curr <= prev:
        return "large"
    if curr.major != prev.major:
        return "large"
    if curr.minor != prev.minor:
        return "medium"
    return "small"


def ha_core_version_satisfies(current: str, required: str) -> bool:
    """True if `current` (Home Assistant Core's own running version,
    always calendar-style) is the same as or newer than `required` (a
    minimum HA version a repository's manifest demands, both HACS and
    its Marketplace successor only ever express this as a plain HA release
    version, see install_manager.py's own _postponed). True on anything
    that doesn't parse as a calendar version on either side: this is only
    ever used to decide whether a *known*-insufficient version has become
    sufficient without re-attempting a real install, never to block one
    that might otherwise be fine, so failing open (try again, worst case
    one wasted attempt re-confirms the same postponed state) beats failing
    closed (stuck postponed forever on a version string that doesn't
    parse)."""
    if not is_calendar_version(current) or not is_calendar_version(required):
        return True
    return _parse_calendar(current) >= _parse_calendar(required)


# Both HACS (a plain-text HacsException message, wrapped into a bare
# HomeAssistantError by its own update.py) and its Marketplace successor
# (a MarketplaceError with a real translation_key/translation_placeholders)
# raise this when a release's own manifest needs a newer HA Core than what's
# actually running, found live 2026-11-02, verified against both
# integrations' real source (hacs/integration's repositories/base.py
# _ensure_download_capabilities, home-assistant/core's marketplace/
# repositories/base.py _check_minimum_version). Checked structurally first
# (Marketplace's own translation_key), the regex only exists for HACS, whose
# own exception carries no translation_key at all, still HACS's own
# generated string (the version comes from its own parsed hacs.json, not
# typed by a person), not arbitrary input.
_MARKETPLACE_MIN_HA_VERSION_KEY = "requires_newer_home_assistant"
_HACS_MIN_HA_VERSION_RE = re.compile(r"requires Home Assistant ([\d.]+) or newer", re.IGNORECASE)


def min_ha_version_required(exception: BaseException) -> str | None:
    """The minimum HA Core version a failed install's own exception says it
    needs, or None if this failure wasn't about that at all, also None for
    an extracted version ha_core_version_satisfies can't actually compare
    (not a plain calendar version), rather than one it can never stop
    reporting as newly-satisfied. Found by code review, 2026-11-02: a
    repository manifest that states this as anything other than a full
    "YYYY.M.P" (e.g. a 2-part "2026.11") makes ha_core_version_satisfies
    fail open on every single evaluation, not just once, the same fixed,
    unparseable string compares the same way forever, so the entity would
    clear self._postponed, re-attempt the same doomed install, and land
    right back in self._postponed every single tick, the exact retry storm
    this feature exists to prevent. Falling through to the ordinary
    backoff-based failure path instead (min_ha_version_required returning
    None here) is strictly better for this case: real backoff, a real
    "Failed updates" entry, no silent forever-loop.

    Shared by install_manager.py's own auto-install path, websocket_api.py's
    manual-install path, and rollout_manager.py's queued-install path
    (found missing one of these three by code review, 2026-11-03: a queued
    Zigbee/tier install that hit this exact failure retried forever on the
    generic backoff instead). A plain function here, not a method on
    InstallManager, specifically so rollout_manager.py can call it directly
    without importing install_manager.py at all (which already imports
    rollout_manager.py, see that module's own docstring for why an install
    failure's own postponed-vs-generic classification can't just live
    there)."""
    if getattr(exception, "translation_key", None) == _MARKETPLACE_MIN_HA_VERSION_KEY:
        placeholders = getattr(exception, "translation_placeholders", None) or {}
        version = placeholders.get("version")
    else:
        match = _HACS_MIN_HA_VERSION_RE.search(str(exception))
        version = match.group(1) if match else None
    return version if version and is_calendar_version(version) else None
