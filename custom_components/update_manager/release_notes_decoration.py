"""Decorates raw release-notes markdown the same way
update-manager-panel.js's own _decorateReleaseNotes does: GitHub's own
renderer turns bare #1234 (issue/PR references) and @username mentions into
real links automatically, and recognizes gitmoji-style :shortcode: text as
an emoji -- ha-markdown (and, for this project's own get_release_notes
service, whatever reads the plain response text) has no idea either of
these repo-relative conventions exist and just shows the literal text
otherwise.

A faithful port of _linkifyGithubReferences/_replaceGithubEmojiShortcodes/
_GITHUB_EMOJI_SHORTCODES, kept pure and HA-independent, same reasoning as
changelog_trim.py -- see that module's own docstring.
"""
from __future__ import annotations

import re

# Not exhaustive (real gemoji has ~1800 entries, not worth bundling here) --
# covers home-assistant/supervisor's own full list, plus the standard
# gitmoji.dev set commit-convention release notes commonly use across many
# other repos too, plus release-drafter's own default "Thanks to our
# contributors" heading (":bow:", confirmed on a real music-assistant/server
# release). An unmapped shortcode is left exactly as written, same graceful
# "can't improve on it, don't break it" treatment as everything else in
# this fallback.
_GITHUB_EMOJI_SHORTCODES = {
    "boom": "\U0001f4a5", "sparkles": "✨", "bug": "\U0001f41b", "gem": "\U0001f48e",
    "package": "\U0001f4e6", "rocket": "\U0001f680", "rotating_light": "\U0001f6a8",
    "hammer_and_wrench": "\U0001f6e0️", "gear": "⚙️", "recycle": "♻️",
    "wastebasket": "\U0001f5d1️", "arrow_up": "⬆️", "arrow_down": "⬇️",
    "tada": "\U0001f389", "fire": "\U0001f525", "white_check_mark": "✅", "warning": "⚠️",
    "memo": "\U0001f4dd", "bulb": "\U0001f4a1", "zap": "⚡", "lock": "\U0001f512",
    "unlock": "\U0001f513", "construction": "\U0001f6a7", "wrench": "\U0001f527", "hammer": "\U0001f528",
    "art": "\U0001f3a8", "lipstick": "\U0001f484", "ambulance": "\U0001f691",
    "heavy_plus_sign": "➕", "heavy_minus_sign": "➖", "pushpin": "\U0001f4cc",
    "construction_worker": "\U0001f477", "chart_with_upwards_trend": "\U0001f4c8",
    "green_heart": "\U0001f49a", "closed_lock_with_key": "\U0001f510", "alien": "\U0001f47d",
    "truck": "\U0001f69a", "page_facing_up": "\U0001f4c4", "bento": "\U0001f371",
    "wheelchair": "♿", "speech_balloon": "\U0001f4ac", "card_file_box": "\U0001f5c3️",
    "loud_sound": "\U0001f50a", "mute": "\U0001f507", "busts_in_silhouette": "\U0001f465",
    "children_crossing": "\U0001f6b8", "building_construction": "\U0001f3d7️",
    "iphone": "\U0001f4f1", "egg": "\U0001f95a", "see_no_evil": "\U0001f648",
    "camera_flash": "\U0001f4f8", "alembic": "⚗️", "mag": "\U0001f50d",
    "label": "\U0001f3f7️", "seedling": "\U0001f331", "triangular_flag_on_post": "\U0001f6a9",
    "goal_net": "\U0001f945", "test_tube": "\U0001f9ea", "stethoscope": "\U0001fa7a", "x": "❌",
    "heavy_check_mark": "✔️", "100": "\U0001f4af", "star": "⭐", "star2": "\U0001f31f",
    "thumbsup": "\U0001f44d", "thumbsdown": "\U0001f44e", "eyes": "\U0001f440", "heart": "❤️",
    "bow": "\U0001f647",
}

_EMOJI_SHORTCODE_RE = re.compile(r":([a-z0-9_+-]+):")

# (?<![\w#[]) -- so this doesn't match in the middle of a longer token (a
# heading like "### 1234" or an already-composed "##1234"), nor inside an
# existing GitHub *reference*-style link definition
# ("[#177201]: https://.../pull/177201", a real shape Home Assistant
# Core's own release notes use) -- without excluding a preceding "[", the
# #1234 *inside* that reference label got linkified too, turning
# "[#177201]: url" into "[[#177201](.../issues/177201)]: url", no longer a
# link definition a markdown renderer recognizes at all.
_ISSUE_REF_RE = re.compile(r"(?<![\w#\[])#(\d+)\b")
# @username -- GitHub handles are alphanumeric/hyphen, 1-39 chars.
# Negative lookbehind on \w/@/./[ so this doesn't fire mid-email-address
# ("user@example.com") or inside an existing "[@username]" reference
# label. Optional trailing "[bot]" captured separately: GitHub's own
# auto-generated release notes ("bumped by @dependabot[bot] in #1234") are
# an extremely common shape. A bot's own real profile lives at
# github.com/apps/{name}, not github.com/{name} (that 404s for most bots).
_MENTION_RE = re.compile(r"(?<![\w@.\[])@([a-zA-Z0-9][a-zA-Z0-9-]{0,38})(\[bot\])?")


def replace_github_emoji_shortcodes(text: str) -> str:
    return _EMOJI_SHORTCODE_RE.sub(lambda m: _GITHUB_EMOJI_SHORTCODES.get(m.group(1), m.group(0)), text)


def linkify_github_references(text: str, owner: str | None, repo: str | None) -> str:
    if not owner or not repo:
        return text
    text = _ISSUE_REF_RE.sub(lambda m: f"[#{m.group(1)}](https://github.com/{owner}/{repo}/issues/{m.group(1)})", text)

    def _mention_replacement(match: re.Match[str]) -> str:
        username, bot_suffix = match.group(1), match.group(2) or ""
        url = f"https://github.com/apps/{username}" if bot_suffix else f"https://github.com/{username}"
        return f"[@{username}{bot_suffix}]({url})"

    return _MENTION_RE.sub(_mention_replacement, text)


def decorate_release_notes(notes: str | None, owner: str | None, repo: str | None) -> str | None:
    """Applies both decorations in one place, same order as the dialog's
    own _decorateReleaseNotes: linkify first, then emoji shortcodes (doing
    it in the other order risks the emoji regex firing inside a URL a
    linkify pass just produced, though none of the mapped shortcodes
    happen to collide with real GitHub path segments today)."""
    if not notes:
        return notes
    return replace_github_emoji_shortcodes(linkify_github_references(notes, owner, repo))
