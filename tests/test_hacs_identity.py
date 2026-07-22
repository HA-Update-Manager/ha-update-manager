"""Tests for the pure, HA-independent GitHub release URL identity extraction."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_MODULE_PATH = (
    Path(__file__).resolve().parent.parent
    / "custom_components" / "update_manager" / "hacs_identity.py"
)
_spec = importlib.util.spec_from_file_location("update_manager_hacs_identity", _MODULE_PATH)
hacs_identity = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hacs_identity)


class TestExtractHacsIdentity:
    def test_basic(self):
        url = "https://github.com/HA-Update-Manager/ha-update-manager/releases/tag/1.2.3"
        assert hacs_identity.extract_hacs_identity(url) == ("HA-Update-Manager", "ha-update-manager", "1.2.3")

    def test_v_prefix_stripped(self):
        url = "https://github.com/owner/repo/releases/tag/v2.0.0"
        assert hacs_identity.extract_hacs_identity(url) == ("owner", "repo", "2.0.0")

    def test_short_form_without_tag_segment(self):
        # Found live 2026-07-22 against ha-update-manager's own update
        # entity: GitHub accepts this shorter form as a real, working URL
        # too, not every integration's release_url uses the canonical
        # releases/tag/<tag> shape.
        url = "https://github.com/HA-Update-Manager/ha-update-manager/releases/v0.1.0"
        assert hacs_identity.extract_hacs_identity(url) == ("HA-Update-Manager", "ha-update-manager", "0.1.0")

    def test_no_v_prefix_left_untouched(self):
        url = "https://github.com/owner/repo/releases/tag/1.2.3"
        assert hacs_identity.extract_hacs_identity(url) == ("owner", "repo", "1.2.3")

    def test_version_starting_with_a_literal_v_word_not_stripped(self):
        # Only a "v"/"V" immediately followed by a digit counts as a
        # version-tag prefix -- a real (if unusual) version that happens to
        # start with a word beginning in v isn't mangled.
        url = "https://github.com/owner/repo/releases/tag/vNext-2026.1"
        assert hacs_identity.extract_hacs_identity(url) == ("owner", "repo", "vNext-2026.1")

    def test_none_input(self):
        assert hacs_identity.extract_hacs_identity(None) is None

    def test_empty_string(self):
        assert hacs_identity.extract_hacs_identity("") is None

    def test_non_github_url(self):
        assert hacs_identity.extract_hacs_identity("https://example.com/changelog") is None

    def test_github_url_wrong_shape(self):
        assert hacs_identity.extract_hacs_identity("https://github.com/owner/repo") is None
        assert hacs_identity.extract_hacs_identity("https://github.com/owner/repo/issues/5") is None

    def test_missing_owner_or_repo(self):
        assert hacs_identity.extract_hacs_identity("https://github.com//repo/releases/tag/1.0.0") is None
