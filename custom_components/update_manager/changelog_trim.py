"""Trims a raw changelog file's text down to just the section(s) covering a
specific version jump, by markdown heading.

A faithful, line-for-line port of update-manager-panel.js's own
_trimChangelogToVersion/_findChangelogHeadingIndex/_splitIntoHeadingSections
-- deliberately not a simplified or "close enough" rewrite: the panel
applies this to every release-notes source it shows (native and
GitHub-compiled alike), and services.py's own get_release_notes service
needs to return the exact same text an automation would otherwise have to
scrape out of the dialog by hand. Kept in its own pure, HA-independent
module (no import here needs `homeassistant` at all) specifically so it's
still unit-testable in this project's pure-Python test suite, the same
reasoning update_status.py/semver.py already follow.

This exists at all because HA core's own SupervisorAddonUpdateEntity.
async_release_notes() (and several native add-on changelog formats like it)
returns its own entire, often years-long changelog file verbatim, not just
the section for the version actually being installed -- confirmed live,
2026-08-02, against two real add-ons (matterbridge-home-assistant-addon,
alexbelgium's mealie), each with different heading shapes HA core's own
first-heading-only regex doesn't recognize.
"""
from __future__ import annotations

import re

_HEADING_LINE_RE = re.compile(r"^#{1,6}[ \t].*$", re.MULTILINE)
_NEXT_HEADING_RE = re.compile(r"^#{1,6}[ \t]", re.MULTILINE)


def _find_changelog_heading_index(text: str, version: str | None) -> int | None:
    """The index of a markdown heading line that *contains* `version`
    somewhere in it (not necessarily as the entire rest of the line) --
    real confirmed heading shapes this needs to match: "## 2026.7.5 -
    2026-07-31" (a trailing date) and "## v3.22.0 (2026-08-01)" (a trailing
    date in parens, plus a "v" prefix). `(?![.\\-\\d])` after the version,
    not a trailing word boundary, so "v3.17.0" doesn't also match inside a
    later "v3.17.0-1" heading (real example, same add-on): a hyphen is a
    non-word character, same as a real line end, so a plain \\b treats
    both as valid boundaries. None when no heading anywhere mentions this
    version at all -- nothing confident to find, not an error."""
    if not version:
        return None
    escaped = re.escape(version)
    match = re.search(rf"^#{{1,6}}[ \t].*\b{escaped}(?![.\-\d])", text, re.MULTILINE)
    return match.start() if match else None


def _split_into_heading_sections(text: str) -> list[str]:
    """Splits a block of raw changelog text into one chunk per top-level
    heading it contains, each running from that heading's own line through
    just before the next one (or the end of the block for the last chunk)
    -- used by trim_changelog_to_version's own downgrade branch below to
    reorder a contiguous newest-first block into the oldest-first reading
    order a downgrade wants, without losing or reflowing any of the
    original text."""
    indices = [m.start() for m in _HEADING_LINE_RE.finditer(text)]
    if not indices:
        return [text]
    return [text[start : indices[i + 1] if i + 1 < len(indices) else len(text)] for i, start in enumerate(indices)]


def trim_changelog_to_version(notes: str | None, from_version: str | None, to_version: str | None) -> str | None:
    """Trims release-notes text down to just the section covering
    to_version, stopping right before from_version's own heading if that's
    found too -- same "compile from target down to (not including)
    from_version" idea as github_release_notes.py's own
    compile_release_range, just for a raw changelog file's own loose
    markdown headings instead of GitHub's structured releases list.
    Returns `notes` completely unchanged whenever to_version's own heading
    can't be found at all -- never guess, same principle as
    compile_release_range: this is only ever a refinement of already-real
    content, never a source of new content, and applying it uniformly to
    every release-notes source (including ones that were already correctly
    scoped, like a single GitHub release's own body, which has no version
    heading in it at all to begin with) is safe by construction for
    exactly that reason."""
    if not notes or not to_version:
        return notes
    start_index = _find_changelog_heading_index(notes, to_version)
    if start_index is None:
        return notes
    after_start_line = notes.find("\n", start_index)
    search_from = len(notes) if after_start_line == -1 else after_start_line + 1
    # A downgrade (from_version newer than to_version) has from_version's
    # own heading appearing *before* to_version's in this newest-first
    # text, not after: every heading from from_version down through
    # to_version's own section, reordered oldest-first (you land on
    # to_version first, then read forward through what you're losing,
    # ending on from_version, the version you were just on) -- the
    # opposite of this text's own newest-first order, so the matched block
    # is split back into its individual heading sections and reversed, not
    # just sliced.
    from_heading_index = _find_changelog_heading_index(notes[:start_index], from_version) if from_version else None
    if from_heading_index is not None:
        next_heading = _NEXT_HEADING_RE.search(notes[search_from:])
        block_end = search_from + next_heading.start() if next_heading else len(notes)
        return "".join(reversed(_split_into_heading_sections(notes[from_heading_index:block_end])))
    if not from_version:
        return notes[start_index:]
    # Searched only from just after to_version's own heading line, not
    # from the very start of `notes` -- from_version's own heading must be
    # a later one, never to_version's own line (a coincidental substring
    # match there would otherwise cut the result down to nothing).
    relative_end_index = _find_changelog_heading_index(notes[search_from:], from_version)
    return notes[start_index:] if relative_end_index is None else notes[start_index : search_from + relative_end_index]
