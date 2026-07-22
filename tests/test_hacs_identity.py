"""Tests for the pure, HA-independent GitHub release URL identity extraction."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

# hacs_identity.py does `from .semver import strip_version_prefix` (both are
# pure, HA-independent modules, see each one's own docstring), so unlike
# semver.py's/staging.py's own tests this needs a real, if minimal, parent
# package registered in sys.modules for that relative import to resolve --
# a bare spec_from_file_location (no package) can't satisfy it.
_PKG_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "update_manager"
_PKG_NAME = "update_manager_test_pkg"
if _PKG_NAME not in sys.modules:
    _pkg = types.ModuleType(_PKG_NAME)
    _pkg.__path__ = [str(_PKG_DIR)]
    sys.modules[_PKG_NAME] = _pkg

_spec = importlib.util.spec_from_file_location(f"{_PKG_NAME}.hacs_identity", _PKG_DIR / "hacs_identity.py")
hacs_identity = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = hacs_identity
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


class TestResolveVotesPath:
    def test_hacs_entity(self):
        url = "https://github.com/owner/repo/releases/tag/1.2.3"
        assert hacs_identity.resolve_votes_path("update.some_integration", url, "1.2.3") == "hacs/owner/repo/1.2.3"

    def test_home_assistant_core_not_misfiled_as_hacs(self):
        # Found by review, 2026-07-22: Core's own release_url matches the
        # generic HACS regex just as readily as a real HACS integration
        # would, so this must be checked by entity_id first, not by shape.
        url = "https://github.com/home-assistant/core/releases/tag/2026.7.3"
        assert (
            hacs_identity.resolve_votes_path("update.home_assistant_core_update", url, "2026.7.3")
            == "home-assistant/core/2026.7.3"
        )

    def test_home_assistant_supervisor(self):
        assert (
            hacs_identity.resolve_votes_path("update.home_assistant_supervisor_update", None, "2026.07.1")
            == "home-assistant/supervisor/2026.07.1"
        )

    def test_home_assistant_os_uses_latest_version_not_release_url(self):
        # No release_url at all (or one that doesn't match a GitHub shape)
        # still resolves correctly for these three, unlike the HACS case,
        # since the version comes from latest_version directly.
        assert (
            hacs_identity.resolve_votes_path("update.home_assistant_operating_system_update", None, "v14.2")
            == "home-assistant/os/14.2"
        )

    def test_unidentifiable_entity(self):
        assert hacs_identity.resolve_votes_path("update.some_integration", None, "1.2.3") is None
