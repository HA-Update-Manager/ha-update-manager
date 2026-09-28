"""Tests for the pure, HA-independent changelog-trimming logic -- a
line-for-line port of update-manager-panel.js's own
_trimChangelogToVersion/_findChangelogHeadingIndex, so these cases mirror
the real, confirmed shapes that JS implementation was built against.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_MODULE_PATH = (
    Path(__file__).resolve().parent.parent
    / "custom_components" / "update_manager" / "changelog_trim.py"
)
_spec = importlib.util.spec_from_file_location("update_manager_changelog_trim", _MODULE_PATH)
changelog_trim = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(changelog_trim)


class TestTrimChangelogToVersion:
    def test_returns_unchanged_when_no_notes_or_no_to_version(self):
        assert changelog_trim.trim_changelog_to_version(None, "1.0.0", "2.0.0") is None
        assert changelog_trim.trim_changelog_to_version("some text", "1.0.0", None) == "some text"

    def test_returns_unchanged_when_to_version_heading_not_found(self):
        notes = "## 1.0.0\n\nSome notes.\n"
        assert changelog_trim.trim_changelog_to_version(notes, "0.9.0", "2.0.0") == notes

    def test_basic_single_section(self):
        notes = "## 2.0.0\n\nNewest.\n\n## 1.0.0\n\nOlder.\n"
        result = changelog_trim.trim_changelog_to_version(notes, "1.0.0", "2.0.0")
        assert result == "## 2.0.0\n\nNewest.\n\n"

    def test_no_from_version_slices_to_end_of_file(self):
        notes = "## 2.0.0\n\nNewest.\n\n## 1.0.0\n\nOlder.\n"
        result = changelog_trim.trim_changelog_to_version(notes, None, "2.0.0")
        assert result == notes

    def test_from_version_not_found_slices_to_end_of_file(self):
        notes = "## 2.0.0\n\nNewest.\n\n## 1.0.0\n\nOlder.\n"
        result = changelog_trim.trim_changelog_to_version(notes, "0.5.0", "2.0.0")
        assert result == notes

    def test_matterbridge_style_heading_with_trailing_date(self):
        """Real confirmed shape: matterbridge-home-assistant-addon's own
        changelog headings read "## 2026.7.5 - 2026-07-31" -- a version
        with no "v" prefix, followed by a trailing date, not the entire
        rest of the line."""
        notes = (
            "## 2026.7.5 - 2026-07-31\n\nFixed a bug.\n\n"
            "## 2026.7.4 - 2026-07-20\n\nOlder fix.\n"
        )
        result = changelog_trim.trim_changelog_to_version(notes, "2026.7.4", "2026.7.5")
        assert result == "## 2026.7.5 - 2026-07-31\n\nFixed a bug.\n\n"

    def test_mealie_style_heading_with_v_prefix_and_parenthesized_date(self):
        """Real confirmed shape: alexbelgium's mealie add-on's own changelog
        headings read "## v3.22.0 (2026-08-01)" -- a "v" prefix plus a
        trailing date in parentheses."""
        notes = (
            "## v3.22.0 (2026-08-01)\n\nNew feature.\n\n"
            "## v3.21.0 (2026-07-15)\n\nOlder feature.\n"
        )
        result = changelog_trim.trim_changelog_to_version(notes, "v3.21.0", "v3.22.0")
        assert result == "## v3.22.0 (2026-08-01)\n\nNew feature.\n\n"

    def test_disambiguates_a_suffixed_version_from_its_own_prefix(self):
        """Real confirmed shape: alexbelgium's mealie add-on has both
        "## v3.17.0-1 (2026-05-10)" and, right below it (older),
        "## v3.17.0 (2026-05-09)". Searching for "v3.17.0" must not match
        inside "v3.17.0-1"'s own heading, which appears earlier (newer) in
        the text."""
        notes = (
            "## v3.17.0-1 (2026-05-10)\n\nPatch.\n\n"
            "## v3.17.0 (2026-05-09)\n\nRelease.\n\n"
            "## v3.16.0 (2026-04-01)\n\nOlder.\n"
        )
        result = changelog_trim.trim_changelog_to_version(notes, "v3.16.0", "v3.17.0")
        assert result == "## v3.17.0 (2026-05-09)\n\nRelease.\n\n"

    def test_downgrade_shows_every_version_given_up_oldest_first(self):
        """A downgrade (from_version newer than to_version) shows every
        version between them, reordered oldest-first: you land on
        to_version first, then read forward through what you're losing,
        ending on from_version, the version you were just on."""
        notes = (
            "## 3.0.0\n\nNewest.\n\n"
            "## 2.0.0\n\nMiddle.\n\n"
            "## 1.0.0\n\nOldest.\n"
        )
        result = changelog_trim.trim_changelog_to_version(notes, "3.0.0", "1.0.0")
        assert result == "## 1.0.0\n\nOldest.\n## 2.0.0\n\nMiddle.\n\n## 3.0.0\n\nNewest.\n\n"
