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


class TestStripImageDimensions:
    def test_strips_width_and_height_from_a_real_github_image_tag(self):
        """Real confirmed shape, frenck/spook v5.12.0: a drag-and-dropped
        screenshot's own raw <img> tag, written by GitHub's release editor."""
        text = (
            '<img width="1600" height="947" alt="image" '
            'src="https://github.com/user-attachments/assets/5cd6daae-51ba-4557-b087-ef9101a920b1" />'
        )
        result = release_notes_decoration.strip_image_dimensions(text)
        assert "width=" not in result
        assert "height=" not in result
        assert 'alt="image"' in result
        assert 'src="https://github.com/user-attachments/assets/5cd6daae-51ba-4557-b087-ef9101a920b1"' in result

    def test_leaves_text_without_an_img_tag_unchanged(self):
        text = "Plain text with a width=100 word that isn't a real attribute at all."
        assert release_notes_decoration.strip_image_dimensions(text) == text

    def test_handles_multiple_image_tags(self):
        text = '<img width="900" height="500" src="a.png"><img width="800" height="400" src="b.png">'
        result = release_notes_decoration.strip_image_dimensions(text)
        assert result == '<img src="a.png"><img src="b.png">'

    def test_leaves_a_small_icon_sized_image_alone(self):
        """Real confirmed shape, frenck/spook v5.12.0: its own row of
        social-media icon links, GitHub's own README-badge convention.
        Stripping broke these live, 2026-11-27: an SVG icon like this
        often has no other natural size to fall back on, and unlike the
        screenshot case, it's never wide enough for max-width:100% to
        ever shrink it in the first place, so nothing here was ever
        mismatched to begin with."""
        text = '<img src="linkedin.svg" width="18" height="18">'
        assert release_notes_decoration.strip_image_dimensions(text) == text

    def test_strips_when_only_one_dimension_is_small(self):
        text = '<img width="1600" src="a.png">'
        result = release_notes_decoration.strip_image_dimensions(text)
        assert result == '<img src="a.png">'


class TestDecorateReleaseNotes:
    def test_returns_none_for_no_notes(self):
        assert release_notes_decoration.decorate_release_notes(None, "acme", "widget") is None

    def test_applies_both_decorations(self):
        result = release_notes_decoration.decorate_release_notes("Thanks @someone :bow: (#1234)", "acme", "widget")
        assert result == "Thanks [@someone](https://github.com/someone) \U0001f647 ([#1234](https://github.com/acme/widget/issues/1234))"

    def test_also_strips_image_dimensions(self):
        result = release_notes_decoration.decorate_release_notes(
            '<img width="1600" height="947" src="a.png">', "acme", "widget"
        )
        assert result == '<img src="a.png">'
