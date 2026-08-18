"""Tests for the pure, HA-independent install_log retention logic."""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

_MODULE_PATH = (
    Path(__file__).resolve().parent.parent
    / "custom_components" / "update_manager" / "install_log_retention.py"
)
_spec = importlib.util.spec_from_file_location("update_manager_install_log_retention", _MODULE_PATH)
retention = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(retention)

NOW = datetime(2026, 8, 18, 12, 0, 0, tzinfo=timezone.utc)


def _entry(entity_id, days_ago, notes="some release notes"):
    return {
        "entity_id": entity_id,
        "installed_at": (NOW - timedelta(days=days_ago)).isoformat(),
        "release_notes": notes,
    }


class TestApplyReleaseNotesRetention:
    def test_recent_entry_keeps_notes(self):
        entries = [_entry("update.a", days_ago=1)]
        retention.apply_release_notes_retention(entries, retention.DEFAULT_POLICY, NOW)
        assert entries[0]["release_notes"] is not None

    def test_old_entry_with_enough_newer_siblings_loses_notes(self):
        # Same entity has 3 entries, all older than the 90-day window: only
        # the 2 most recent (the per-entity floor) should keep notes.
        entries = [
            _entry("update.a", days_ago=400),
            _entry("update.a", days_ago=200),
            _entry("update.a", days_ago=100),
        ]
        retention.apply_release_notes_retention(entries, retention.DEFAULT_POLICY, NOW)
        assert entries[0]["release_notes"] is None
        assert entries[1]["release_notes"] is not None
        assert entries[2]["release_notes"] is not None

    def test_rarely_updating_entity_keeps_its_last_two_regardless_of_age(self):
        entries = [_entry("update.rare", days_ago=900)]
        retention.apply_release_notes_retention(entries, retention.DEFAULT_POLICY, NOW)
        assert entries[0]["release_notes"] is not None

    def test_busy_entity_does_not_crowd_out_a_quiet_entity(self):
        # A chatty entity with many recent entries must not affect whether
        # a different, quiet entity's own old entry keeps its floor.
        entries = [_entry("update.busy", days_ago=d) for d in range(50)]
        entries.append(_entry("update.quiet", days_ago=500))
        retention.apply_release_notes_retention(entries, retention.DEFAULT_POLICY, NOW)
        assert entries[-1]["release_notes"] is not None

    def test_idempotent_on_already_stripped_entries(self):
        entries = [_entry("update.a", days_ago=400, notes=None)]
        # Should not raise, and should stay None.
        retention.apply_release_notes_retention(entries, retention.DEFAULT_POLICY, NOW)
        assert entries[0]["release_notes"] is None

    def test_unparseable_installed_at_is_treated_as_not_fresh(self):
        entries = [
            {"entity_id": "update.a", "installed_at": "not-a-date", "release_notes": "x"},
            _entry("update.a", days_ago=1),
            _entry("update.a", days_ago=2),
        ]
        retention.apply_release_notes_retention(entries, retention.DEFAULT_POLICY, NOW)
        # Falls outside the per-entity floor (the other two are newer/kept
        # first since we walk newest-first... but this one is index 0,
        # oldest position) and fails the freshness check, so it's stripped.
        assert entries[0]["release_notes"] is None


class TestEnforceByteBackstop:
    def test_does_nothing_under_the_limit(self):
        entries = [_entry("update.a", days_ago=1)]
        before = json.dumps(entries)
        retention.enforce_byte_backstop(entries, NOW, max_bytes=10_000_000)
        assert json.dumps(entries) == before

    def test_degrades_notes_before_dropping_entries(self):
        # Many old entries for the *same* entity, all with sizeable notes
        # and all past the per-entity floor -- degrading the release-notes
        # policy alone (stripping all but the most recent) must be enough,
        # no entries dropped.
        entries = [_entry("update.a", days_ago=200, notes="x" * 2000) for _ in range(50)]
        count_before = len(entries)
        retention.enforce_byte_backstop(entries, NOW, max_bytes=20_000)
        assert len(entries) == count_before
        assert retention.serialized_size(entries) <= 20_000

    def test_drops_oldest_entries_when_notes_alone_are_not_enough(self):
        # 200 distinct entities, one entry each -- the per-entity floor
        # protects every single one of them, so degrading the release-notes
        # policy can't strip anything at all. Must fall back to dropping
        # the oldest entries outright.
        entries = [_entry(f"update.e{i}", days_ago=1, notes="x" * 500) for i in range(200)]
        retention.enforce_byte_backstop(entries, NOW, max_bytes=5_000)
        assert retention.serialized_size(entries) <= 5_000
        assert len(entries) < 200
        # Dropped from the front (index 0, install_log.py's own
        # oldest-first order) -- the earliest entity should be gone.
        assert all(entry["entity_id"] != "update.e0" for entry in entries)
