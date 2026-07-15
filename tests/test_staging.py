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


class TestEvaluateStaging:
    def test_major_is_always_blocked(self):
        result = staging.evaluate_staging("major", available_since=NOW, now=NOW)
        assert result.status == "blocked"
        assert result.remaining is None

    def test_unknown_is_always_blocked(self):
        result = staging.evaluate_staging("unknown", available_since=NOW, now=NOW)
        assert result.status == "blocked"

    def test_major_blocked_even_after_a_long_time(self):
        # Blocked means "needs a manual decision", not "waiting" -- time
        # passing never resolves it on its own.
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

    def test_custom_rules_override_defaults(self):
        rules = staging.StagingRules(patch_wait=timedelta(days=1), minor_wait=timedelta(days=14))
        result = staging.evaluate_staging("patch", available_since=NOW, now=NOW, rules=rules)
        assert result.status == "waiting"
        assert result.remaining == timedelta(days=1)

    def test_zero_wait_custom_rule_for_minor(self):
        rules = staging.StagingRules(patch_wait=timedelta(0), minor_wait=timedelta(0))
        result = staging.evaluate_staging("minor", available_since=NOW, now=NOW, rules=rules)
        assert result.status == "ready"
