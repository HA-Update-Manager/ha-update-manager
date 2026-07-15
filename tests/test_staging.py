"""Tests for the pure, HA-independent staging logic."""
from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

_MODULE_PATH = (
    Path(__file__).resolve().parent.parent
    / "custom_components" / "update_manager" / "staging.py"
)
_spec = importlib.util.spec_from_file_location("update_manager_staging", _MODULE_PATH)
staging = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(staging)

NOW = datetime(2026, 7, 15, 12, 0, 0, tzinfo=timezone.utc)


class TestEvaluateStagingDefaults:
    def test_major_is_blocked_by_default(self):
        result = staging.evaluate_staging("major", available_since=NOW, now=NOW)
        assert result.status == "blocked"
        assert result.remaining is None

    def test_unknown_is_blocked_by_default(self):
        result = staging.evaluate_staging("unknown", available_since=NOW, now=NOW)
        assert result.status == "blocked"

    def test_major_blocked_by_default_even_after_a_long_time(self):
        # Blocked means "needs a manual decision", not "waiting" -- time
        # passing never resolves it on its own under the default rules.
        long_ago = NOW - timedelta(days=365)
        result = staging.evaluate_staging("major", available_since=long_ago, now=NOW)
        assert result.status == "blocked"

    def test_patch_ready_immediately_with_default_rules(self):
        result = staging.evaluate_staging("patch", available_since=NOW, now=NOW)
        assert result.status == "ready"
        assert result.remaining is None

    def test_minor_waiting_right_after_appearing(self):
        result = staging.evaluate_staging("minor", available_since=NOW, now=NOW)
        assert result.status == "waiting"
        assert result.remaining == timedelta(days=7)

    def test_minor_still_waiting_partway_through(self):
        now = NOW + timedelta(days=3)
        result = staging.evaluate_staging("minor", available_since=NOW, now=now)
        assert result.status == "waiting"
        assert result.remaining == timedelta(days=4)

    def test_minor_ready_exactly_at_the_wait_boundary(self):
        now = NOW + timedelta(days=7)
        result = staging.evaluate_staging("minor", available_since=NOW, now=now)
        assert result.status == "ready"
        assert result.remaining is None

    def test_minor_ready_well_past_the_wait(self):
        now = NOW + timedelta(days=30)
        result = staging.evaluate_staging("minor", available_since=NOW, now=now)
        assert result.status == "ready"


class TestEvaluateStagingCustomRules:
    def test_custom_rules_override_patch_and_minor(self):
        rules = staging.StagingRules(
            patch_wait=timedelta(days=1),
            minor_wait=timedelta(days=14),
            major_wait=None,
            unknown_wait=None,
        )
        result = staging.evaluate_staging("patch", available_since=NOW, now=NOW, rules=rules)
        assert result.status == "waiting"
        assert result.remaining == timedelta(days=1)

    def test_zero_wait_custom_rule_for_minor(self):
        rules = staging.StagingRules(
            patch_wait=timedelta(0),
            minor_wait=timedelta(0),
            major_wait=None,
            unknown_wait=None,
        )
        result = staging.evaluate_staging("minor", available_since=NOW, now=NOW, rules=rules)
        assert result.status == "ready"

    def test_major_can_be_given_a_real_wait_instead_of_always_blocked(self):
        # Nothing in this module hardcodes "major is always blocked" --
        # that's just what DEFAULT_RULES chooses. A user who explicitly
        # wants major updates to become "ready" after a (probably long)
        # wait can configure that.
        rules = staging.StagingRules(
            patch_wait=timedelta(0),
            minor_wait=timedelta(days=7),
            major_wait=timedelta(days=30),
            unknown_wait=None,
        )
        waiting = staging.evaluate_staging("major", available_since=NOW, now=NOW, rules=rules)
        assert waiting.status == "waiting"
        assert waiting.remaining == timedelta(days=30)

        ready = staging.evaluate_staging(
            "major", available_since=NOW, now=NOW + timedelta(days=30), rules=rules
        )
        assert ready.status == "ready"

    def test_unknown_can_also_be_given_a_real_wait(self):
        rules = staging.StagingRules(
            patch_wait=timedelta(0),
            minor_wait=timedelta(days=7),
            major_wait=None,
            unknown_wait=timedelta(days=14),
        )
        result = staging.evaluate_staging("unknown", available_since=NOW, now=NOW, rules=rules)
        assert result.status == "waiting"
        assert result.remaining == timedelta(days=14)

    def test_patch_can_be_forced_to_always_blocked_too(self):
        # Symmetric with the above: any jump type can be locked to "always
        # blocked" via None, not just major/unknown.
        rules = staging.StagingRules(
            patch_wait=None,
            minor_wait=timedelta(days=7),
            major_wait=None,
            unknown_wait=None,
        )
        result = staging.evaluate_staging("patch", available_since=NOW, now=NOW, rules=rules)
        assert result.status == "blocked"
