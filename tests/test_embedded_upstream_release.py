"""Tests for the pure, HA-independent embedded-upstream-release detection
-- a port of update-manager-panel.js's own _findEmbeddedUpstreamRelease, so
these cases mirror the real, confirmed shapes that JS implementation was
built against.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_MODULE_PATH = (
    Path(__file__).resolve().parent.parent
    / "custom_components" / "update_manager" / "embedded_upstream_release.py"
)
_spec = importlib.util.spec_from_file_location("update_manager_embedded_upstream_release", _MODULE_PATH)
embedded_upstream_release = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(embedded_upstream_release)


class TestFindEmbeddedUpstreamRelease:
    def test_returns_none_for_no_notes(self):
        assert embedded_upstream_release.find_embedded_upstream_release(None, None, None, None) is None
        assert embedded_upstream_release.find_embedded_upstream_release("", None, None, None) is None

    def test_zigbee2mqtt_style_link_with_exact_tag(self):
        """Real confirmed shape: a Zigbee2MQTT add-on's own release notes
        link straight to Koenkk/zigbee2mqtt's exact release."""
        notes = "Updated Zigbee2MQTT to version [2.13.0](https://github.com/Koenkk/zigbee2mqtt/releases/tag/2.13.0)"
        found = embedded_upstream_release.find_embedded_upstream_release(notes, None, None, None)
        assert found == embedded_upstream_release.EmbeddedUpstreamRelease(
            owner="Koenkk", repo="zigbee2mqtt", tag="2.13.0"
        )

    def test_mealie_style_bare_releases_link_with_no_tag(self):
        """Real confirmed shape: a Mealie add-on's own release notes link
        to mealie-recipes/mealie's general releases page, plain text, not
        wrapped in markdown link syntax, and no specific tag."""
        notes = "changelog : https://github.com/mealie-recipes/mealie/releases"
        found = embedded_upstream_release.find_embedded_upstream_release(notes, None, None, None)
        assert found == embedded_upstream_release.EmbeddedUpstreamRelease(
            owner="mealie-recipes", repo="mealie", tag=None
        )

    def test_changelog_blob_link_carries_no_tag(self):
        """Real confirmed shape: a matterbridge-home-assistant-addon
        example links a sub-dependency's own changelog this way."""
        notes = "Updated matterbridge-hass to [1.4.0](https://github.com/Luligu/matterbridge-hass/blob/main/CHANGELOG.md#140)"
        found = embedded_upstream_release.find_embedded_upstream_release(notes, None, None, None)
        assert found == embedded_upstream_release.EmbeddedUpstreamRelease(owner="Luligu", repo="matterbridge-hass", tag=None)

    def test_excludes_own_repo_self_reference(self):
        notes = "See [1.0.0](https://github.com/frenck/spook/releases/tag/1.0.0)"
        found = embedded_upstream_release.find_embedded_upstream_release(notes, "frenck", "spook", None)
        assert found is None

    def test_excludes_self_reference_by_from_version_when_own_repo_unknown(self):
        """Real confirmed shape: a Supervisor add-on entity never sets
        release_url at all, so own_owner/own_repo aren't available to
        check against -- from_version catches the same self-reference a
        second way. Real example: music-assistant/server 2.9.13's only
        embedded link was "_Changes since
        [2.9.12](.../music-assistant/server/releases/tag/2.9.12)_"."""
        notes = "_Changes since [2.9.12](https://github.com/music-assistant/server/releases/tag/2.9.12)_"
        found = embedded_upstream_release.find_embedded_upstream_release(notes, None, None, "2.9.12")
        assert found is None

    def test_v_prefix_ignored_when_comparing_tag_to_from_version(self):
        notes = "_Changes since [v2.9.12](https://github.com/music-assistant/server/releases/tag/v2.9.12)_"
        found = embedded_upstream_release.find_embedded_upstream_release(notes, None, None, "2.9.12")
        assert found is None

    def test_latest_is_not_a_real_tag(self):
        notes = "See https://github.com/Koenkk/zigbee2mqtt/releases/latest"
        found = embedded_upstream_release.find_embedded_upstream_release(notes, None, None, None)
        assert found == embedded_upstream_release.EmbeddedUpstreamRelease(owner="Koenkk", repo="zigbee2mqtt", tag=None)

    def test_more_than_one_distinct_repo_is_ambiguous(self):
        notes = (
            "Bumped [a](https://github.com/one/repo/releases/tag/1.0.0) "
            "and [b](https://github.com/two/repo/releases/tag/2.0.0)"
        )
        found = embedded_upstream_release.find_embedded_upstream_release(notes, None, None, None)
        assert found is None

    def test_same_repo_mentioned_twice_is_not_ambiguous(self):
        notes = (
            "See https://github.com/Koenkk/zigbee2mqtt/releases/tag/2.13.0 "
            "and also https://github.com/Koenkk/zigbee2mqtt/releases/tag/2.13.0 again"
        )
        found = embedded_upstream_release.find_embedded_upstream_release(notes, None, None, None)
        assert found == embedded_upstream_release.EmbeddedUpstreamRelease(
            owner="Koenkk", repo="zigbee2mqtt", tag="2.13.0"
        )

    def test_unresolvable_domain_still_counts_toward_ambiguity(self):
        """A matterbridge.io-style link that can't be resolved to a GitHub
        repo still counts as *a* distinct reference, so a real, resolvable
        GitHub link mentioned alongside it isn't mistaken for "exactly
        one" -- picking it anyway would show the wrong project's notes
        with no indication anything was left out."""
        notes = (
            "See https://matterbridge.io/CHANGELOG.html#140 and "
            "[matterbridge-hass](https://github.com/Luligu/matterbridge-hass/blob/main/CHANGELOG.md#140)"
        )
        found = embedded_upstream_release.find_embedded_upstream_release(notes, None, None, None)
        assert found is None
