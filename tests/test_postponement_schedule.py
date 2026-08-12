"""Tests for the pure, HA-independent postponement schedule logic."""
from __future__ import annotations

import importlib.util
from datetime import datetime, time, timezone
from pathlib import Path

_MODULE_PATH = (
    Path(__file__).resolve().parent.parent
    / "custom_components" / "update_manager" / "postponement_schedule.py"
)
_spec = importlib.util.spec_from_file_location("update_manager_postponement_schedule", _MODULE_PATH)
postponement_schedule = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(postponement_schedule)

DayRule = postponement_schedule.DayRule
PostponementSchedule = postponement_schedule.PostponementSchedule
EMPTY_SCHEDULE = postponement_schedule.EMPTY_SCHEDULE
next_allowed_ready = postponement_schedule.next_allowed_ready

# 2026-08-11 is a Tuesday.
TUESDAY = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)


def _schedule(enabled_days: dict[int, DayRule] | None = None) -> PostponementSchedule:
    """Builds a schedule with every day disabled except the ones named
    (0=Monday .. 6=Sunday), keyed by index for readability at each call
    site instead of a bare 7-tuple literal."""
    days = [DayRule(False, None)] * 7
    for index, rule in (enabled_days or {}).items():
        days[index] = rule
    return PostponementSchedule(days=tuple(days))


class TestEmptySchedule:
    def test_no_days_enabled_never_restricts_anything(self):
        assert next_allowed_ready(EMPTY_SCHEDULE, TUESDAY) is None

    def test_equivalent_explicit_all_disabled_schedule(self):
        assert next_allowed_ready(_schedule(), TUESDAY) is None


class TestWaitDeadlineAlreadyWithinAnAllowedWindow:
    """next_allowed_ready never returns None for a non-empty schedule -- it
    resolves *which* instant matters, the caller (coordinator.py's own
    _apply_schedule_gate) decides whether that's already arrived by
    comparing it against the real current time itself. These cases all
    resolve back to wait_deadline unchanged, the caller's own signal that
    nothing is actually being held back."""

    def test_today_enabled_no_time_resolves_to_wait_deadline_itself(self):
        schedule = _schedule({1: DayRule(True, None)})  # Tuesday, any time
        assert next_allowed_ready(schedule, TUESDAY) == TUESDAY

    def test_today_enabled_time_exactly_wait_deadline(self):
        schedule = _schedule({1: DayRule(True, time(12, 0))})
        assert next_allowed_ready(schedule, TUESDAY) == TUESDAY


class TestWaitDeadlineStillAhead:
    def test_today_enabled_time_still_ahead_returns_today_at_that_time(self):
        schedule = _schedule({1: DayRule(True, time(17, 0))})
        result = next_allowed_ready(schedule, TUESDAY)
        assert result == TUESDAY.replace(hour=17, minute=0)


class TestFutureDay:
    def test_next_enabled_day_with_no_time_returns_its_own_midnight(self):
        schedule = _schedule({5: DayRule(True, None)})  # Saturday
        result = next_allowed_ready(schedule, TUESDAY)
        assert result == datetime(2026, 8, 15, 0, 0, tzinfo=timezone.utc)

    def test_next_enabled_day_with_time_returns_that_moment(self):
        schedule = _schedule({5: DayRule(True, time(10, 0))})  # Saturday 10:00
        result = next_allowed_ready(schedule, TUESDAY)
        assert result == datetime(2026, 8, 15, 10, 0, tzinfo=timezone.utc)

    def test_picks_the_nearest_of_several_enabled_days(self):
        schedule = _schedule(
            {3: DayRule(True, time(9, 0)), 5: DayRule(True, time(10, 0))}  # Thursday, Saturday
        )
        result = next_allowed_ready(schedule, TUESDAY)
        assert result == datetime(2026, 8, 13, 9, 0, tzinfo=timezone.utc)  # Thursday


class TestTimedDayMissedOnceWaitDeadlineIsPastIt:
    """A day WITH a time set is a strict checkpoint: wait_deadline landing
    on that same day but after its own set time means this occurrence is
    missed entirely, not "still fine, any time after also counts" the way a
    no-time day works (TestWaitDeadlineAlreadyWithinAnAllowedWindow's own
    no-time case)."""

    def test_wait_deadline_same_day_after_the_set_time_rolls_to_next_week(self):
        schedule = _schedule({1: DayRule(True, time(10, 0))})  # Tuesday 10:00
        wait_deadline = TUESDAY.replace(hour=12, minute=28)  # Tuesday 12:28
        result = next_allowed_ready(schedule, wait_deadline)
        assert result == datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)  # next Tuesday


class TestWeekWrapAround:
    def test_only_the_wait_deadlines_own_weekday_enabled_and_already_missed(self):
        # Only Tuesday enabled, wait_deadline itself already past its own
        # 10:00 -- needs to wrap a full 7 days to find that same weekday
        # again, not just scan the other 6 (all disabled).
        schedule = _schedule({1: DayRule(True, time(10, 0))})
        wait_deadline = TUESDAY.replace(hour=14)
        result = next_allowed_ready(schedule, wait_deadline)
        assert result == datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)  # next Tuesday

    def test_sunday_only_enabled_from_a_monday(self):
        monday = datetime(2026, 8, 10, 8, 0, tzinfo=timezone.utc)
        schedule = _schedule({6: DayRule(True, time(10, 0))})  # Sunday
        result = next_allowed_ready(schedule, monday)
        assert result == datetime(2026, 8, 16, 10, 0, tzinfo=timezone.utc)
