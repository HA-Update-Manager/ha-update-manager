"""Tests for the pure, HA-independent auto-install announcement logic."""
from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

_MODULE_PATH = (
    Path(__file__).resolve().parent.parent
    / "custom_components" / "update_manager" / "announcer.py"
)
_spec = importlib.util.spec_from_file_location("update_manager_announcer", _MODULE_PATH)
announcer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(announcer)

NOW = datetime(2026, 7, 15, 12, 0, 0, tzinfo=timezone.utc)
WAIT = timedelta(hours=24)


def _existing(to_version="2.0.0", announced_at=NOW):
    return announcer.PendingAnnouncement(
        entity_id="update.thing",
        to_version=to_version,
        announced_at=announced_at,
        execute_at=announced_at + WAIT,
    )


class TestSizeAutoInstallEnabled:
    def test_reads_correct_field_per_size(self):
        rules = announcer.AutoInstallRules(
            small_auto_install=True,
            medium_auto_install=False,
            big_auto_install=True,
            announce_wait=WAIT,
        )
        assert announcer.size_auto_install_enabled("small", rules) is True
        assert announcer.size_auto_install_enabled("medium", rules) is False
        assert announcer.size_auto_install_enabled("big", rules) is True


class TestDecideAction:
    def test_not_ready_with_no_existing_announcement_does_nothing(self):
        action = announcer.decide_action(
            is_ready=False, remaining=None, auto_install_enabled=True, installable=True,
            existing=None, cancelled_to_version=None, current_to_version="2.0.0",
            now=NOW, announce_wait=WAIT,
        )
        assert action == "none"

    def test_no_longer_ready_removes_existing_announcement(self):
        # E.g. the wait rule changed, or the update resolved itself --
        # nothing to fire on anymore.
        action = announcer.decide_action(
            is_ready=False, remaining=None, auto_install_enabled=True, installable=True,
            existing=_existing(), cancelled_to_version=None, current_to_version="2.0.0",
            now=NOW, announce_wait=WAIT,
        )
        assert action == "remove"

    def test_auto_install_disabled_removes_existing_announcement(self):
        action = announcer.decide_action(
            is_ready=True, remaining=None, auto_install_enabled=False, installable=True,
            existing=_existing(), cancelled_to_version=None, current_to_version="2.0.0",
            now=NOW, announce_wait=WAIT,
        )
        assert action == "remove"

    def test_not_installable_removes_existing_announcement(self):
        # UpdateEntityFeature.INSTALL missing -- must never be acted on,
        # even if it was somehow announced before (e.g. feature flags
        # changed underneath us).
        action = announcer.decide_action(
            is_ready=True, remaining=None, auto_install_enabled=True, installable=False,
            existing=_existing(), cancelled_to_version=None, current_to_version="2.0.0",
            now=NOW, announce_wait=WAIT,
        )
        assert action == "remove"

    def test_eligible_with_no_existing_announcement_announces(self):
        action = announcer.decide_action(
            is_ready=True, remaining=None, auto_install_enabled=True, installable=True,
            existing=None, cancelled_to_version=None, current_to_version="2.0.0",
            now=NOW, announce_wait=WAIT,
        )
        assert action == "announce"

    def test_existing_announcement_not_yet_due_does_nothing(self):
        action = announcer.decide_action(
            is_ready=True, remaining=None, auto_install_enabled=True, installable=True,
            existing=_existing(announced_at=NOW), cancelled_to_version=None,
            current_to_version="2.0.0", now=NOW + timedelta(hours=1), announce_wait=WAIT,
        )
        assert action == "none"

    def test_existing_announcement_exactly_due_executes(self):
        action = announcer.decide_action(
            is_ready=True, remaining=None, auto_install_enabled=True, installable=True,
            existing=_existing(announced_at=NOW), cancelled_to_version=None,
            current_to_version="2.0.0", now=NOW + WAIT, announce_wait=WAIT,
        )
        assert action == "execute"

    def test_existing_announcement_well_past_due_executes(self):
        action = announcer.decide_action(
            is_ready=True, remaining=None, auto_install_enabled=True, installable=True,
            existing=_existing(announced_at=NOW), cancelled_to_version=None,
            current_to_version="2.0.0", now=NOW + timedelta(days=30), announce_wait=WAIT,
        )
        assert action == "execute"

    def test_target_version_changed_underneath_removes_stale_announcement(self):
        # A newer version appeared before the older one was ever installed
        # -- clear the stale announcement rather than firing on it; a fresh
        # "announce" follows once this runs again with existing=None.
        action = announcer.decide_action(
            is_ready=True, remaining=None, auto_install_enabled=True, installable=True,
            existing=_existing(to_version="2.0.0"), cancelled_to_version=None,
            current_to_version="2.1.0", now=NOW, announce_wait=WAIT,
        )
        assert action == "remove"

    def test_cancelled_version_with_no_existing_announcement_stays_quiet(self):
        action = announcer.decide_action(
            is_ready=True, remaining=None, auto_install_enabled=True, installable=True,
            existing=None, cancelled_to_version="2.0.0", current_to_version="2.0.0",
            now=NOW, announce_wait=WAIT,
        )
        assert action == "none"

    def test_cancelled_version_with_existing_announcement_removes_it(self):
        action = announcer.decide_action(
            is_ready=True, remaining=None, auto_install_enabled=True, installable=True,
            existing=_existing(to_version="2.0.0"), cancelled_to_version="2.0.0",
            current_to_version="2.0.0", now=NOW, announce_wait=WAIT,
        )
        assert action == "remove"

    def test_cancellation_does_not_apply_to_a_newer_version(self):
        # Cancelling 2.0.0 shouldn't silently suppress 2.1.0 too.
        action = announcer.decide_action(
            is_ready=True, remaining=None, auto_install_enabled=True, installable=True,
            existing=None, cancelled_to_version="2.0.0", current_to_version="2.1.0",
            now=NOW, announce_wait=WAIT,
        )
        assert action == "announce"

    def test_not_ready_but_within_announce_wait_of_ready_announces(self):
        # Still "waiting" (staging.py), but little enough is left that the
        # cancel window should start now rather than once fully ready --
        # otherwise the total time-to-install becomes wait + announce_wait
        # instead of reading as just the uitsteltermijn itself.
        action = announcer.decide_action(
            is_ready=False, remaining=timedelta(hours=1), auto_install_enabled=True, installable=True,
            existing=None, cancelled_to_version=None, current_to_version="2.0.0",
            now=NOW, announce_wait=WAIT,
        )
        assert action == "announce"

    def test_not_ready_and_beyond_announce_wait_of_ready_does_nothing(self):
        action = announcer.decide_action(
            is_ready=False, remaining=timedelta(days=5), auto_install_enabled=True, installable=True,
            existing=None, cancelled_to_version=None, current_to_version="2.0.0",
            now=NOW, announce_wait=WAIT,
        )
        assert action == "none"


class TestStartAnnouncement:
    def test_sets_execute_at_using_announce_wait_when_already_ready(self):
        result = announcer.start_announcement("update.thing", "2.0.0", NOW, WAIT)
        assert result.entity_id == "update.thing"
        assert result.to_version == "2.0.0"
        assert result.announced_at == NOW
        assert result.execute_at == NOW + WAIT

    def test_anchors_to_natural_ready_time_when_it_leaves_more_than_a_full_announce_wait(self):
        # wait still has 48 hours left, more than the 24h announce_wait --
        # execute_at should land on the natural ready time (in 48h), not just
        # 24h beyond now.
        result = announcer.start_announcement(
            "update.thing", "2.0.0", NOW, WAIT, remaining=timedelta(hours=48)
        )
        assert result.execute_at == NOW + timedelta(hours=48)

    def test_announce_wait_wins_when_remaining_is_shorter(self):
        # Only 2 hours left on the uitsteltermijn -- the user must still get
        # the full configured announce_wait to react, so execute_at can't
        # land sooner than that.
        result = announcer.start_announcement(
            "update.thing", "2.0.0", NOW, WAIT, remaining=timedelta(hours=2)
        )
        assert result.execute_at == NOW + WAIT
