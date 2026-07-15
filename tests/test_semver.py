"""Tests for the pure, HA-independent semver classification logic."""
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

    def test_rejects_ha_core_calendar_version_shape(self):
        # This is valid strict-semver *syntax* (three dot-separated ints),
        # but is_ha_core_calendar_version is what excludes it elsewhere --
        # parse_semver itself doesn't know about that distinction, and
        # correctly still parses its numeric core.
        assert semver.parse_semver("2026.7.1") == (2026, 7, 1)


class TestIsHaCoreCalendarVersion:
    def test_matches_calendar_shape(self):
        assert semver.is_ha_core_calendar_version("2026.7.1")
        assert semver.is_ha_core_calendar_version("2026.12.0")
        assert semver.is_ha_core_calendar_version("v2026.7.1")

    def test_rejects_month_out_of_range(self):
        assert not semver.is_ha_core_calendar_version("2026.13.1")
        assert not semver.is_ha_core_calendar_version("2026.0.1")

    def test_rejects_year_out_of_plausible_range(self):
        assert not semver.is_ha_core_calendar_version("1.7.1")

    def test_does_not_match_ordinary_semver(self):
        assert not semver.is_ha_core_calendar_version("1.2.3")


class TestClassifyVersionJump:
    def test_patch(self):
        assert semver.classify_version_jump("1.2.3", "1.2.4") == "patch"

    def test_minor(self):
        assert semver.classify_version_jump("1.2.3", "1.3.0") == "minor"

    def test_major(self):
        assert semver.classify_version_jump("1.2.3", "2.0.0") == "major"

    def test_minor_bump_resets_patch_comparison(self):
        # Only the highest-order differing component should count.
        assert semver.classify_version_jump("1.2.9", "1.3.0") == "minor"

    def test_major_bump_takes_precedence_over_minor_and_patch(self):
        assert semver.classify_version_jump("1.2.9", "2.0.1") == "major"

    def test_no_change_is_unknown(self):
        assert semver.classify_version_jump("1.2.3", "1.2.3") == "unknown"

    def test_downgrade_is_unknown(self):
        assert semver.classify_version_jump("1.2.3", "1.2.0") == "unknown"
        assert semver.classify_version_jump("2.0.0", "1.9.9") == "unknown"

    def test_non_semver_previous_is_unknown(self):
        assert semver.classify_version_jump("not-a-version", "1.2.3") == "unknown"

    def test_non_semver_current_is_unknown(self):
        assert semver.classify_version_jump("1.2.3", "not-a-version") == "unknown"

    def test_ha_core_calendar_version_is_always_unknown(self):
        # Even though 2026.7.1 -> 2026.8.0 parses as a clean "minor" bump
        # syntactically, HA Core's calendar versioning carries no such
        # meaning -- conservatively "unknown" regardless of which side
        # (or both) is calendar-shaped.
        assert semver.classify_version_jump("2026.7.1", "2026.8.0") == "unknown"
        assert semver.classify_version_jump("2026.7.1", "2027.1.0") == "unknown"
        assert semver.classify_version_jump("1.2.3", "2026.7.1") == "unknown"

    def test_prerelease_of_new_major_is_still_major(self):
        assert semver.classify_version_jump("1.2.3", "2.0.0-beta.1") == "major"
