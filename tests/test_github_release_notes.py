"""Tests for the pure, HA-independent GitHub release-URL parsing."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

# github_release_notes.py does `from .semver import strip_version_prefix`
# (both pure, HA-independent modules, see each one's own docstring), so this
# needs the same minimal parent package registered in sys.modules as
# test_hacs_identity.py's own workaround, for that relative import to
# resolve.
_PKG_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "update_manager"
_PKG_NAME = "update_manager_test_pkg_github_release_notes"
if _PKG_NAME not in sys.modules:
    _pkg = types.ModuleType(_PKG_NAME)
    _pkg.__path__ = [str(_PKG_DIR)]
    sys.modules[_PKG_NAME] = _pkg


def _load(module_name):
    spec = importlib.util.spec_from_file_location(f"{_PKG_NAME}.{module_name}", _PKG_DIR / f"{module_name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


github_release_notes = _load("github_release_notes")


class TestParseReleaseUrl:
    def test_canonical_tag_form(self):
        url = "https://github.com/owner/repo/releases/tag/v1.2.3"
        assert github_release_notes.parse_release_url(url) == ("owner", "repo", "v1.2.3")

    def test_short_form_without_tag_segment(self):
        url = "https://github.com/owner/repo/releases/1.2.3"
        assert github_release_notes.parse_release_url(url) == ("owner", "repo", "1.2.3")

    def test_v_prefix_not_stripped(self):
        # Unlike hacs_identity.extract_hacs_identity, this must keep the tag
        # exactly as written -- GitHub's own /releases/tags/{tag} API needs
        # an exact match, a normalized tag would 404 against a repo that
        # really does tag with a "v" prefix.
        url = "https://github.com/home-assistant/core/releases/tag/v2026.7.4"
        owner, repo, tag = github_release_notes.parse_release_url(url)
        assert tag == "v2026.7.4"

    def test_none_input(self):
        assert github_release_notes.parse_release_url(None) is None

    def test_empty_string(self):
        assert github_release_notes.parse_release_url("") is None

    def test_non_github_url(self):
        assert github_release_notes.parse_release_url("https://example.com/releases/1.0.0") is None

    def test_github_url_wrong_shape(self):
        assert github_release_notes.parse_release_url("https://github.com/owner/repo") is None

    def test_missing_owner_or_repo(self):
        assert github_release_notes.parse_release_url("https://github.com//repo/releases/tag/1.0.0") is None


class TestCompileReleaseRange:
    def test_compiles_every_release_down_to_from_version_exclusive(self):
        releases = [
            {"tag_name": "v3.0.0", "body": "third"},
            {"tag_name": "v2.0.0", "body": "second"},
            {"tag_name": "v1.0.0", "body": "first"},
        ]
        result = github_release_notes.compile_release_range(releases, from_version="1.0.0", target_tag="v3.0.0")
        assert result == "## v3.0.0\n\nthird\n\n## v2.0.0\n\nsecond"

    def test_target_tag_not_found_returns_none(self):
        releases = [{"tag_name": "v1.0.0", "body": "first"}]
        assert github_release_notes.compile_release_range(releases, from_version="0.1.0", target_tag="v9.9.9") is None

    def test_from_version_never_found_returns_partial_range(self):
        releases = [
            {"tag_name": "v2.0.0", "body": "second"},
            {"tag_name": "v1.0.0", "body": "first"},
        ]
        result = github_release_notes.compile_release_range(releases, from_version="0.1.0", target_tag="v2.0.0")
        assert result == "## v2.0.0\n\nsecond\n\n## v1.0.0\n\nfirst"

    def test_target_equals_from_version_returns_none(self):
        releases = [{"tag_name": "v1.0.0", "body": "first"}]
        result = github_release_notes.compile_release_range(releases, from_version="1.0.0", target_tag="v1.0.0")
        assert result is None

    def test_v_prefix_mismatch_between_tags_and_from_version_still_matches(self):
        releases = [
            {"tag_name": "24.0.1", "body": "no v prefix in tag"},
            {"tag_name": "v23.0.0", "body": "has v prefix in tag"},
        ]
        result = github_release_notes.compile_release_range(releases, from_version="v23.0.0", target_tag="24.0.1")
        assert result == "## 24.0.1\n\nno v prefix in tag"

    def test_releases_with_empty_body_are_skipped_but_dont_break_the_walk(self):
        releases = [
            {"tag_name": "v3.0.0", "body": ""},
            {"tag_name": "v2.0.0", "body": None},
            {"tag_name": "v1.0.0", "body": "first"},
        ]
        result = github_release_notes.compile_release_range(releases, from_version="0.1.0", target_tag="v3.0.0")
        assert result == "## v1.0.0\n\nfirst"

    def test_all_bodies_empty_returns_none(self):
        releases = [{"tag_name": "v1.0.0", "body": ""}]
        result = github_release_notes.compile_release_range(releases, from_version="0.1.0", target_tag="v1.0.0")
        assert result is None

    def test_skipped_prereleases_are_left_out_of_the_walk(self):
        # Real shape confirmed live against home-assistant/operating-system,
        # 2026-08-01: jumping 18.1 -> 18.2 otherwise dragged in 18.2.rc1's
        # own changelog too, even though that rc was never actually installed.
        releases = [
            {"tag_name": "18.2", "body": "stable 18.2", "prerelease": False},
            {"tag_name": "18.2.rc1", "body": "rc1 notes", "prerelease": True},
            {"tag_name": "18.1", "body": "stable 18.1", "prerelease": False},
        ]
        result = github_release_notes.compile_release_range(releases, from_version="18.1", target_tag="18.2")
        assert result == "## 18.2\n\nstable 18.2"

    def test_target_itself_a_prerelease_is_still_included(self):
        releases = [
            {"tag_name": "18.2.rc1", "body": "rc1 notes", "prerelease": True},
            {"tag_name": "18.1", "body": "stable 18.1", "prerelease": False},
        ]
        result = github_release_notes.compile_release_range(releases, from_version="18.1", target_tag="18.2.rc1")
        assert result == "## 18.2.rc1\n\nrc1 notes"

    def test_downgrade_with_no_intermediate_releases_shows_target_then_from(self):
        # Real shape confirmed live, 2026-08-02: a 7.1.10 -> 7.1.9 downgrade
        # used to walk forward from 7.1.9 (never finding 7.1.10, which sits
        # *earlier* in this newest-first list) all the way to the very
        # first release this repo ever tagged, instead of stopping correctly.
        # Reconsidered the same day: rather than showing only 7.1.9's own
        # release alone, show both endpoints, oldest first -- what you're
        # landing on, then what you're giving up.
        releases = [
            {"tag_name": "7.1.10", "body": "notes for 7.1.10"},
            {"tag_name": "7.1.9", "body": "notes for 7.1.9"},
            {"tag_name": "7.1.8", "body": "notes for 7.1.8"},
            {"tag_name": "1.0.0", "body": "the very first release"},
        ]
        result = github_release_notes.compile_release_range(releases, from_version="7.1.10", target_tag="7.1.9")
        assert result == "## 7.1.9\n\nnotes for 7.1.9\n\n## 7.1.10\n\nnotes for 7.1.10"

    def test_downgrade_with_intermediate_releases_shows_all_of_them_oldest_first(self):
        releases = [
            {"tag_name": "3.0.0", "body": "notes for 3.0.0"},
            {"tag_name": "2.0.0", "body": "notes for 2.0.0"},
            {"tag_name": "1.0.0", "body": "notes for 1.0.0"},
        ]
        result = github_release_notes.compile_release_range(releases, from_version="3.0.0", target_tag="1.0.0")
        assert result == "## 1.0.0\n\nnotes for 1.0.0\n\n## 2.0.0\n\nnotes for 2.0.0\n\n## 3.0.0\n\nnotes for 3.0.0"

    def test_downgrade_skips_prerelease_stepping_stones_but_keeps_both_endpoints(self):
        releases = [
            {"tag_name": "3.0.0", "body": "notes for 3.0.0", "prerelease": False},
            {"tag_name": "2.0.0-beta1", "body": "beta notes", "prerelease": True},
            {"tag_name": "1.0.0", "body": "notes for 1.0.0", "prerelease": False},
        ]
        result = github_release_notes.compile_release_range(releases, from_version="3.0.0", target_tag="1.0.0")
        assert result == "## 1.0.0\n\nnotes for 1.0.0\n\n## 3.0.0\n\nnotes for 3.0.0"

    def test_downgrade_target_itself_a_prerelease_is_still_included(self):
        releases = [
            {"tag_name": "2.0.0", "body": "notes for 2.0.0", "prerelease": False},
            {"tag_name": "1.0.0-rc1", "body": "rc notes", "prerelease": True},
        ]
        result = github_release_notes.compile_release_range(releases, from_version="2.0.0", target_tag="1.0.0-rc1")
        assert result == "## 1.0.0-rc1\n\nrc notes\n\n## 2.0.0\n\nnotes for 2.0.0"

    def test_downgrade_with_no_body_anywhere_returns_none(self):
        releases = [
            {"tag_name": "2.0.0", "body": ""},
            {"tag_name": "1.0.0", "body": ""},
        ]
        result = github_release_notes.compile_release_range(releases, from_version="2.0.0", target_tag="1.0.0")
        assert result is None

    def test_from_version_not_in_page_still_walks_forward_normally(self):
        # from_version genuinely unknown (not a downgrade we can detect,
        # nor provably an upgrade) -- existing "partial-but-real range"
        # behavior unaffected by the new downgrade check, since an
        # unmatched from_index is simply None, never less than start_index.
        releases = [
            {"tag_name": "2.0.0", "body": "notes for 2.0.0"},
            {"tag_name": "1.5.0", "body": "notes for 1.5.0"},
        ]
        result = github_release_notes.compile_release_range(releases, from_version="0.1.0", target_tag="2.0.0")
        assert result == "## 2.0.0\n\nnotes for 2.0.0\n\n## 1.5.0\n\nnotes for 1.5.0"


class TestFindReleaseByVersion:
    def test_finds_matching_release(self):
        releases = [
            {"tag_name": "v2.0.0", "body": "second"},
            {"tag_name": "v1.0.0", "body": "first"},
        ]
        result = github_release_notes.find_release_by_version(releases, "1.0.0")
        assert result == {"tag_name": "v1.0.0", "body": "first"}

    def test_v_prefix_mismatch_still_matches(self):
        releases = [{"tag_name": "24.0.1", "body": "no v prefix"}]
        result = github_release_notes.find_release_by_version(releases, "v24.0.1")
        assert result == {"tag_name": "24.0.1", "body": "no v prefix"}

    def test_no_match_returns_none(self):
        releases = [{"tag_name": "v1.0.0", "body": "first"}]
        assert github_release_notes.find_release_by_version(releases, "9.9.9") is None

    def test_empty_releases_returns_none(self):
        assert github_release_notes.find_release_by_version([], "1.0.0") is None
