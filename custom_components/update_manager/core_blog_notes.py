"""Pure, HA-independent parsing for Home Assistant Core's own monthly
release-notes blog post (home-assistant/home-assistant.io), used for the
"Open release announcement" link on a Core update specifically -- see
hacs_identity.py's own corrected_release_url docstring for the underlying
bug this works around (Core's own native release_url is a fixed "always
latest" URL, useless for anything version-specific).

Two source files, both in home-assistant/home-assistant.io, both fetched by
the caller (websocket_api.py), parsed here:
- source/changelogs/core-{major}.{minor}.markdown: one per monthly release,
  shared by every patch within that month, deterministic filename from any
  full version string (see major_minor). Contains a link to the actual
  blog post -- used instead of guessing the blog post's own filename
  (which embeds its exact publish date, not derivable from the version
  alone) or scanning the whole _posts/ directory for it.
- source/_posts/{date}-release-{major}{minor}.markdown: the actual blog
  post, once its path is known from the changelog link above. Its own
  frontmatter `description` field is the intro text; a specific patch's own
  "### {version} - {Month} {Day}" heading (only present for a patch, never
  a .0 release) is where that patch's own anchor comes from.

Confirmed stable across every release checked, 2025.1 through 2026.8, not
assumed from a single example -- see each function's own docstring for
which exact release(s) grounded that check.
"""
from __future__ import annotations

import re

_BLOG_URL_RE = re.compile(r"\((/blog/\d{4}/\d{2}/\d{2}/release-[a-z0-9]+/)\)")
_BLOG_PATH_RE = re.compile(r"^/blog/(\d{4})/(\d{2})/(\d{2})/([a-z0-9-]+)/$")
_DESCRIPTION_RE = re.compile(r'^description:\s*"((?:[^"\\]|\\.)*)"\s*$', re.MULTILINE)


def major_minor(version: str) -> str:
    """"2026.7.3" -> "2026.7" -- home-assistant.io's own changelog/blog
    files are one per monthly release, shared by every patch within that
    same month. Callers are expected to have already stripped any "v"
    prefix (semver.py's strip_version_prefix), same normalization every
    other version-string consumer in this project already applies before
    handing a version to a version-shaped function."""
    parts = version.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else version


def extract_blog_path(changelog_markdown: str) -> str | None:
    """The /blog/YYYY/MM/DD/release-XXXXX/ path linked from a Core
    changelog file's own intro text (source/changelogs/core-{major}.
    {minor}.markdown), confirmed stable across every release checked,
    2025.1 through 2026.8: "For a summary in a more readable format
    [Release notes blog for this release](/blog/...)." -- regardless of
    the exact surrounding wording, confirmed to vary release to release
    (sometimes a colon, sometimes a blank line before the link); the link
    markup itself never does. None if the expected link isn't found at all
    -- callers fall back to the version-specific GitHub releases tag link
    instead, never show a broken/guessed URL."""
    match = _BLOG_URL_RE.search(changelog_markdown)
    return match.group(1) if match else None


def post_source_path(blog_path: str) -> str | None:
    """"/blog/2026/07/01/release-20267/" ->
    "source/_posts/2026-07-01-release-20267.markdown" -- the blog path
    itself (extract_blog_path's own return value) already carries the
    post's real publish date, which the version string alone never could
    (a release's exact publish day varies month to month, no way to derive
    it from "2026.7" alone) -- turning that same path into the matching
    source filename needs no extra lookup. None if blog_path doesn't match
    the expected shape at all (defensive: extract_blog_path's own regex
    already guarantees this shape today, but a caller passing something
    else by mistake should get None, not a wrong path)."""
    match = _BLOG_PATH_RE.match(blog_path)
    if match is None:
        return None
    year, month, day, slug = match.groups()
    return f"source/_posts/{year}-{month}-{day}-{slug}.markdown"


def extract_description(post_markdown: str) -> str | None:
    """The blog post's own frontmatter `description` field -- a short,
    on-topic, no-jargon summary written by HA's own team specifically for
    this purpose, confirmed present and double-quoted across every release
    checked, 2025.1 through 2026.8. Deliberately not the actual prose intro
    further down the post (after the frontmatter): that's personal, varies
    wildly in tone by author, and regularly includes unrelated asides
    (livestream announcements, conference plugs) that have nothing to do
    with what changed in the release -- confirmed live against both the
    2026.7 and 2026.8 posts, not assumed."""
    match = _DESCRIPTION_RE.search(post_markdown)
    return match.group(1) if match else None


def find_patch_heading(post_markdown: str, version: str) -> str | None:
    """The exact "### {version} - {Month} {Day}" heading text for one
    specific patch version within a Core monthly blog post's own "Patch
    releases" section (e.g. "2026.7.1 - July 3") -- confirmed this exact
    heading shape for every patch of the 2026.7 release, 2026-08-07.
    Returns the full heading text (for slugify_heading to turn into an
    anchor), not the slug itself, so this stays two separate, individually
    testable steps. None if this exact patch version has no such heading (a
    .0 release itself is never listed here, or the post's format changed)
    -- callers fall back to the blog post's own bare URL, no anchor, rather
    than guessing."""
    escaped = re.escape(version)
    match = re.search(rf"^###\s+({escaped}\s*-\s*.+?)\s*$", post_markdown, re.MULTILINE)
    return match.group(1) if match else None


def slugify_heading(heading: str) -> str:
    """Jekyll/kramdown's own auto-generated heading-anchor slug: lowercase,
    every "." removed outright (not replaced with anything), every
    remaining space becomes "-" (an existing "-" stays a literal "-", so a
    " - " sequence becomes "---": space->-, the existing -, space->-).
    Confirmed against a real, working anchor on the live site, 2026-08-07:
    "2026.7.1 - July 3" -> "202671---july-3" -- kramdown doesn't publish
    this algorithm anywhere obvious, this was verified against the actual
    page, not derived from documentation."""
    return re.sub(r"[^a-z0-9\s-]", "", heading.lower()).replace(" ", "-")
