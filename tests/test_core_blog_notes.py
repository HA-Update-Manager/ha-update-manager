"""Tests for the pure, HA-independent Core release-notes-blog parsing."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_MODULE_PATH = (
    Path(__file__).resolve().parent.parent
    / "custom_components" / "update_manager" / "core_blog_notes.py"
)
_spec = importlib.util.spec_from_file_location("update_manager_core_blog_notes", _MODULE_PATH)
core_blog_notes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(core_blog_notes)

# Real excerpts (2026-08-07), from home-assistant/home-assistant.io's own
# source/changelogs/core-2026.7.markdown and source/_posts/
# 2026-07-01-release-20267.markdown -- not synthetic, so a real future
# format change would actually be caught here rather than only live.
_CHANGELOG_EXCERPT = """---
title: Full changelog for Home Assistant 2026.7
description: Detailed changelog for the Home Assistant 2026.7 release
replace_regex: \\s\\(\\[?[a-z0-9\\-\\s_]+\\]?\\)$
---

These are all the changes included in the Home Assistant 2026.7 release.
For a summary in a more readable format
[Release notes blog for this release](/blog/2026/07/01/release-20267/).
"""

_CHANGELOG_EXCERPT_WITH_COLON_AND_BLANK_LINE = """---
title: Full changelog for Home Assistant Core 2025.1
description: Detailed changelog for the Home Assistant Core 2025.1 release
---

These are all the changes included in the Home Assistant Core 2025.1 release.
For a summary in a more readable format:

[Release notes blog for this release](/blog/2025/01/03/release-20251/).
"""

_POST_FRONTMATTER = """---
layout: post
title: "2026.7: Automations that speak your language"
description: "Purpose-specific triggers and conditions graduate from Labs to become the new default, letting your automations describe what you want instead of the technical building blocks underneath."
date: 2026-07-01 00:00:00
author: Franck Nijhof
---

Home Assistant 2026.7! 🎉
"""

_POST_PATCH_SECTION = """## Patch releases

We will also release patch releases for Home Assistant 2026.7 in July.

### 2026.7.1 - July 3

- Proximity: Fix/improve matching against trackers ([@kbuck1] - [#172602])

### 2026.7.2 - July 10

- Some other fix ([@someone] - [#123456])
"""


class TestMajorMinor:
    def test_strips_patch_component(self):
        assert core_blog_notes.major_minor("2026.7.3") == "2026.7"

    def test_dot_zero_release_unchanged(self):
        assert core_blog_notes.major_minor("2026.7.0") == "2026.7"

    def test_already_major_minor(self):
        assert core_blog_notes.major_minor("2026.7") == "2026.7"


class TestExtractBlogPath:
    def test_basic(self):
        assert core_blog_notes.extract_blog_path(_CHANGELOG_EXCERPT) == "/blog/2026/07/01/release-20267/"

    def test_tolerates_colon_and_blank_line_variant(self):
        # Real wording drift found between 2025.1 and 2026.7's own
        # changelog files -- the link markup itself doesn't change, only
        # the sentence around it.
        assert (
            core_blog_notes.extract_blog_path(_CHANGELOG_EXCERPT_WITH_COLON_AND_BLANK_LINE)
            == "/blog/2025/01/03/release-20251/"
        )

    def test_none_when_link_missing(self):
        assert core_blog_notes.extract_blog_path("Nothing relevant here.") is None


class TestPostSourcePath:
    def test_basic(self):
        assert (
            core_blog_notes.post_source_path("/blog/2026/07/01/release-20267/")
            == "source/_posts/2026-07-01-release-20267.markdown"
        )

    def test_none_for_unexpected_shape(self):
        assert core_blog_notes.post_source_path("/blog/not-a-real-path/") is None


class TestExtractDescription:
    def test_basic(self):
        description = core_blog_notes.extract_description(_POST_FRONTMATTER)
        assert description is not None
        assert description.startswith("Purpose-specific triggers and conditions")
        assert "🎉" not in description  # the prose intro further down, not this

    def test_none_when_missing(self):
        assert core_blog_notes.extract_description("---\ntitle: X\n---\n") is None


class TestFindPatchHeading:
    def test_finds_the_matching_patch(self):
        assert core_blog_notes.find_patch_heading(_POST_PATCH_SECTION, "2026.7.1") == "2026.7.1 - July 3"

    def test_finds_a_different_patch_in_the_same_post(self):
        assert core_blog_notes.find_patch_heading(_POST_PATCH_SECTION, "2026.7.2") == "2026.7.2 - July 10"

    def test_none_for_a_dot_zero_version_never_listed_here(self):
        assert core_blog_notes.find_patch_heading(_POST_PATCH_SECTION, "2026.7.0") is None

    def test_none_for_a_patch_not_in_this_post(self):
        assert core_blog_notes.find_patch_heading(_POST_PATCH_SECTION, "2026.7.9") is None


class TestSlugifyHeading:
    def test_real_confirmed_example(self):
        # Verified against the actual, working anchor on the live site,
        # 2026-08-07: https://www.home-assistant.io/blog/2026/07/01/
        # release-20267/#202671---july-3
        assert core_blog_notes.slugify_heading("2026.7.1 - July 3") == "202671---july-3"

    def test_two_digit_day(self):
        assert core_blog_notes.slugify_heading("2026.7.2 - July 10") == "202672---july-10"
