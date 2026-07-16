"""Tests for the pure, HA-independent version-size classification logic."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_MODULE_PATH = (
    Path(__file__).resolve().parent.parent
    / "custom_components" / "update_manager" / "semver.py"
)
_spec = importlib.util.spec_from_file_location("update_manager_semver", _MODULE_PATH)
semver = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(semver)


class TestParseSemver:
    def test_basic(self):
        assert semver.parse_semver("1.2.3") == (1, 2, 3)

    def test_v_prefix_stripped(self):
        assert semver.parse_semver("v1.2.3") == (1, 2, 3)
        assert semver.parse_semver("V1.2.3") == (1, 2, 3)

    def test_zero_versions(self):
        assert semver.parse_semver("0.0.0") == (0, 0, 0)

    def test_prerelease_and_build_metadata_ignored_for_core(self):
        assert semver.parse_semver("1.2.3-beta.1") == (1, 2, 3)
        assert semver.parse_semver("1.2.3+build.5") == (1, 2, 3)
        assert semver.parse_semver("1.2.3-beta.1+build.5") == (1, 2, 3)

    def test_rejects_leading_zeros(self):
        # Strict semver: a numeric component with a leading zero (other
        # than a bare "0") is invalid, not "helpfully" reinterpreted.
        assert semver.parse_semver("1.02.3") is None
        assert semver.parse_semver("01.2.3") is None

    def test_rejects_two_part_version(self):
        assert semver.parse_semver("1.2") is None

    def test_rejects_four_part_version(self):
        assert semver.parse_semver("1.2.3.4") is None

    def test_rejects_non_numeric_component(self):
        assert semver.parse_semver("1.2.x") is None

    def test_rejects_empty_string(self):
        assert semver.parse_semver("") is None

    def test_rejects_calendar_version_shape(self):
        # This is valid strict-semver *syntax* (three dot-separated ints),
        # but is_calendar_version is what excludes it elsewhere -- parse_semver
        # itself doesn't know about that distinction, and correctly still
        # parses its numeric core.
        assert semver.parse_semver("2026.7.1") == (2026, 7, 1)


class TestIsCalendarVersion:
    def test_matches_calendar_shape(self):
        assert semver.is_calendar_version("2026.7.1")
        assert semver.is_calendar_version("2026.12.0")
        assert semver.is_calendar_version("v2026.7.1")

    def test_rejects_month_out_of_range(self):
        assert not semver.is_calendar_version("2026.13.1")
        assert not semver.is_calendar_version("2026.0.1")

    def test_rejects_year_out_of_plausible_range(self):
        assert not semver.is_calendar_version("1.7.1")

    def test_does_not_match_ordinary_semver(self):
        assert not semver.is_calendar_version("1.2.3")


class TestIsGitCommitVersion:
    def test_matches_typical_short_hash(self):
        assert semver.is_git_commit_version("4c6e21e")
        assert semver.is_git_commit_version("a8b49eb")

    def test_matches_longer_abbreviations(self):
        # Git auto-expands the abbreviation length as needed to stay unique
        # in a larger repo -- not fixed at 7.
        assert semver.is_git_commit_version("4c6e21ea9")
        assert semver.is_git_commit_version("4c6e21ea9b3d5f7a1c2e4b6d8f0a1b2c3d4e5f6a")

    def test_rejects_too_short(self):
        assert not semver.is_git_commit_version("4c6e2")

    def test_rejects_pure_digits(self):
        # A plain numeric build counter shouldn't be mistaken for a commit
        # hash just because every digit is also a valid hex character.
        assert not semver.is_git_commit_version("123456")
        assert not semver.is_git_commit_version("1234567890")

    def test_rejects_dotted_versions(self):
        assert not semver.is_git_commit_version("1.2.3")
        assert not semver.is_git_commit_version("2026.7.1")

    def test_rejects_non_hex_characters(self):
        assert not semver.is_git_commit_version("4c6e21g")


class TestClassifyVersionSize:
    def test_small(self):
        assert semver.classify_version_size("1.2.3", "1.2.4") == "small"

    def test_medium(self):
        assert semver.classify_version_size("1.2.3", "1.3.0") == "medium"

    def test_big(self):
        assert semver.classify_version_size("1.2.3", "2.0.0") == "big"

    def test_medium_bump_resets_small_comparison(self):
        # Only the highest-order differing component should count.
        assert semver.classify_version_size("1.2.9", "1.3.0") == "medium"

    def test_big_bump_takes_precedence_over_medium_and_small(self):
        assert semver.classify_version_size("1.2.9", "2.0.1") == "big"

    def test_no_change_is_big(self):
        assert semver.classify_version_size("1.2.3", "1.2.3") == "big"

    def test_downgrade_is_big(self):
        assert semver.classify_version_size("1.2.3", "1.2.0") == "big"
        assert semver.classify_version_size("2.0.0", "1.9.9") == "big"

    def test_non_semver_previous_is_big(self):
        assert semver.classify_version_size("not-a-version", "1.2.3") == "big"

    def test_non_semver_current_is_big(self):
        assert semver.classify_version_size("1.2.3", "not-a-version") == "big"

    def test_calendar_same_year_and_month_is_small(self):
        assert semver.classify_version_size("2026.7.1", "2026.7.2") == "small"

    def test_calendar_month_change_is_medium(self):
        assert semver.classify_version_size("2026.7.1", "2026.8.0") == "medium"

    def test_calendar_year_rollover_is_medium_not_big(self):
        # A year rollover is just another month boundary in this scheme's
        # own release cadence -- not a signal of more risk than any other
        # monthly release, so this is deliberately capped at "medium", the
        # same as any other month-to-month jump, never "big".
        assert semver.classify_version_size("2026.12.3", "2027.1.0") == "medium"

    def test_calendar_downgrade_is_big(self):
        assert semver.classify_version_size("2026.8.0", "2026.7.1") == "big"

    def test_mixed_calendar_and_semver_is_big(self):
        # Genuinely ambiguous rather than a jump we can meaningfully name --
        # shouldn't normally happen for the same entity in practice.
        assert semver.classify_version_size("1.2.3", "2026.7.1") == "big"
        assert semver.classify_version_size("2026.7.1", "1.2.3") == "big"

    def test_prerelease_of_new_big_is_still_big(self):
        assert semver.classify_version_size("1.2.3", "2.0.0-beta.1") == "big"

    def test_commit_hashes_on_both_sides_is_medium(self):
        assert semver.classify_version_size("4c6e21e", "a8b49eb") == "medium"

    def test_identical_commit_hashes_is_big(self):
        # No real jump to classify, same conservative treatment as an
        # identical semver/calendar re-announcement.
        assert semver.classify_version_size("4c6e21e", "4c6e21e") == "big"

    def test_mixed_commit_and_semver_is_big(self):
        assert semver.classify_version_size("4c6e21e", "1.2.3") == "big"
        assert semver.classify_version_size("1.2.3", "4c6e21e") == "big"
