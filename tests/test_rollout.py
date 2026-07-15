"""Tests for the pure, HA-independent rollout-pacing queue logic."""
from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_MODULE_PATH = (
    Path(__file__).resolve().parent.parent
    / "custom_components" / "update_manager" / "rollout.py"
)
_spec = importlib.util.spec_from_file_location("update_manager_rollout", _MODULE_PATH)
rollout = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rollout)

NOW = datetime(2026, 7, 15, 12, 0, 0, tzinfo=timezone.utc)
WAIT = timedelta(hours=2)


class TestBuildQueue:
    def test_all_entries_start_pending(self):
        queue = rollout.build_queue(["a", "b", "c"], WAIT)
        assert len(queue.entries) == 3
        assert all(entry.installed_at is None for entry in queue.entries)

    def test_preserves_order(self):
        queue = rollout.build_queue(["c", "a", "b"], WAIT)
        assert [e.device_id for e in queue.entries] == ["c", "a", "b"]


class TestNextReadyDevice:
    def test_first_device_ready_immediately_no_wait_needed(self):
        queue = rollout.build_queue(["a", "b", "c"], WAIT)
        assert rollout.next_ready_device(queue, NOW) == "a"

    def test_empty_queue_returns_none(self):
        queue = rollout.build_queue([], WAIT)
        assert rollout.next_ready_device(queue, NOW) is None

    def test_second_device_blocked_right_after_first_installs(self):
        queue = rollout.build_queue(["a", "b"], WAIT)
        queue = rollout.mark_installed(queue, "a", NOW)
        assert rollout.next_ready_device(queue, NOW) is None

    def test_second_device_still_blocked_partway_through_wait(self):
        queue = rollout.build_queue(["a", "b"], WAIT)
        queue = rollout.mark_installed(queue, "a", NOW)
        assert rollout.next_ready_device(queue, NOW + timedelta(hours=1)) is None

    def test_second_device_ready_exactly_at_wait_boundary(self):
        queue = rollout.build_queue(["a", "b"], WAIT)
        queue = rollout.mark_installed(queue, "a", NOW)
        assert rollout.next_ready_device(queue, NOW + WAIT) == "b"

    def test_second_device_ready_well_past_wait(self):
        queue = rollout.build_queue(["a", "b"], WAIT)
        queue = rollout.mark_installed(queue, "a", NOW)
        assert rollout.next_ready_device(queue, NOW + timedelta(days=1)) == "b"

    def test_pacing_measured_from_most_recent_install_not_the_first(self):
        queue = rollout.build_queue(["a", "b", "c"], WAIT)
        queue = rollout.mark_installed(queue, "a", NOW)
        queue = rollout.mark_installed(queue, "b", NOW + WAIT)
        # Only WAIT has passed since b (the most recent), not since a.
        assert rollout.next_ready_device(queue, NOW + WAIT + timedelta(minutes=1)) is None
        assert rollout.next_ready_device(queue, NOW + WAIT + WAIT) == "c"

    def test_all_installed_returns_none(self):
        queue = rollout.build_queue(["a"], WAIT)
        queue = rollout.mark_installed(queue, "a", NOW)
        assert rollout.next_ready_device(queue, NOW + timedelta(days=365)) is None

    def test_zero_wait_makes_every_device_ready_immediately(self):
        queue = rollout.build_queue(["a", "b", "c"], timedelta(0))
        queue = rollout.mark_installed(queue, "a", NOW)
        assert rollout.next_ready_device(queue, NOW) == "b"


class TestMarkInstalled:
    def test_raises_for_unknown_device(self):
        queue = rollout.build_queue(["a"], WAIT)
        with pytest.raises(ValueError):
            rollout.mark_installed(queue, "does-not-exist", NOW)

    def test_raises_for_already_installed_device(self):
        queue = rollout.build_queue(["a"], WAIT)
        queue = rollout.mark_installed(queue, "a", NOW)
        with pytest.raises(ValueError):
            rollout.mark_installed(queue, "a", NOW + timedelta(hours=1))

    def test_does_not_mutate_the_original_queue(self):
        original = rollout.build_queue(["a", "b"], WAIT)
        rollout.mark_installed(original, "a", NOW)
        assert all(entry.installed_at is None for entry in original.entries)


class TestIsComplete:
    def test_false_when_entries_pending(self):
        queue = rollout.build_queue(["a", "b"], WAIT)
        queue = rollout.mark_installed(queue, "a", NOW)
        assert not rollout.is_complete(queue)

    def test_true_when_all_installed(self):
        queue = rollout.build_queue(["a", "b"], WAIT)
        queue = rollout.mark_installed(queue, "a", NOW)
        queue = rollout.mark_installed(queue, "b", NOW)
        assert rollout.is_complete(queue)

    def test_true_for_empty_queue(self):
        queue = rollout.build_queue([], WAIT)
        assert rollout.is_complete(queue)
