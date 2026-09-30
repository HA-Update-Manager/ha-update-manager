"""Tests for the pure, HA-independent release-notes decoration logic -- a
port of update-manager-panel.js's own _decorateReleaseNotes/
_linkifyGithubReferences/_replaceGithubEmojiShortcodes.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_MODULE_PATH = (
    Path(__file__).resolve().parent.parent
    / "custom_components" / "update_manager" / "release_notes_decoration.py"
)
_spec = importlib.util.spec_from_file_location("update_manager_release_notes_decoration", _MODULE_PATH)
release_notes_decoration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release_notes_decoration)


class TestReplaceGithubEmojiShortcodes:
    def test_replaces_known_shortcode(self):
        assert release_notes_decoration.replace_github_emoji_shortcodes("Thanks :bow:") == "Thanks \U0001f647"

    def test_leaves_unknown_shortcode_unchanged(self):
        text = "Not a real one: :not_a_real_emoji:"
        assert release_notes_decoration.replace_github_emoji_shortcodes(text) == text

    def test_replaces_multiple_shortcodes(self):
        result = release_notes_decoration.replace_github_emoji_shortcodes(":boom: Breaking Changes :sparkles:")
        assert result == "\U0001f4a5 Breaking Changes ✨"


class TestLinkifyGithubReferences:
    def test_returns_unchanged_without_owner_or_repo(self):
        text = "See #1234 and @someone"
        assert release_notes_decoration.linkify_github_references(text, None, None) == text
        assert release_notes_decoration.linkify_github_references(text, "owner", None) == text

    def test_linkifies_issue_reference(self):
        result = release_notes_decoration.linkify_github_references("Fixed in #1234.", "acme", "widget")
        assert result == "Fixed in [#1234](https://github.com/acme/widget/issues/1234)."

    def test_linkifies_mention(self):
        result = release_notes_decoration.linkify_github_references("Thanks @someone!", "acme", "widget")
        assert result == "Thanks [@someone](https://github.com/someone)!"

    def test_bot_mention_links_to_the_app_profile(self):
        """Real confirmed shape: "bumped by @dependabot[bot] in #1234"."""
        result = release_notes_decoration.linkify_github_references("by @dependabot[bot]", "acme", "widget")
        assert result == "by [@dependabot[bot]](https://github.com/apps/dependabot)"

    def test_does_not_match_inside_an_email_address(self):
        text = "Contact user@example.com for help."
        assert release_notes_decoration.linkify_github_references(text, "acme", "widget") == text

    def test_does_not_double_linkify_a_reference_style_link_definition(self):
        """Real confirmed shape, Home Assistant Core 2026.8.1: notes written
        with GitHub's reference-style links ("[#177201]: https://.../pull/177201")
        must not have the #1234 *inside* the label linkified too."""
        text = "([@shtefko] - [#177201])\n\n[#177201]: https://github.com/home-assistant/core/pull/177201"
        result = release_notes_decoration.linkify_github_references(text, "home-assistant", "core")
        assert "[#177201]: https://github.com/home-assistant/core/pull/177201" in result
        assert "[[#177201]" not in result


class TestDecorateReleaseNotes:
    def test_returns_none_for_no_notes(self):
        assert release_notes_decoration.decorate_release_notes(None, "acme", "widget") is None

    def test_applies_both_decorations(self):
        result = release_notes_decoration.decorate_release_notes("Thanks @someone :bow: (#1234)", "acme", "widget")
        assert result == "Thanks [@someone](https://github.com/someone) \U0001f647 ([#1234](https://github.com/acme/widget/issues/1234))"
