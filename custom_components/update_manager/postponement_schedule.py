"""Optional, shared (not per-size) schedule of allowed weekdays/times an
update is permitted to become "ready" on, layered on top of staging.py's own
per-size wait period, not in place of it -- issue #4: someone who wants the
schedule alone to decide sets that size's own wait to 0 instead, reusing the
existing mechanism rather than adding a second one. Composed by coordinator.py
right after evaluate_staging's own result, the same "independent gates,
ANDed together" shape rollout_manager.py's tier gate/Zigbee gate composition
already uses -- staging.py itself is untouched.

Kept free of any homeassistant import, same reasoning as staging.py/
semver.py -- see tests/test_postponement_schedule.py.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import NamedTuple


class DayRule(NamedTuple):
    enabled: bool
    # None (with enabled=True) means "any time that day" -- once that day
    # itself arrives, nothing further restricts it.
    time: time | None


class PostponementSchedule(NamedTuple):
    # Length 7, index 0 = Monday .. 6 = Sunday -- matches datetime.weekday()
    # directly, no translation table needed at the call site.
    days: tuple[DayRule, DayRule, DayRule, DayRule, DayRule, DayRule, DayRule]


# Every day disabled -- the default, fully-optional state. An instance that's
# never touched this setting gets exactly this, and next_allowed_ready always
# returns None for it, so behavior is identical to not having this feature at
# all.
EMPTY_SCHEDULE = PostponementSchedule(days=tuple(DayRule(False, None) for _ in range(7)))  # type: ignore[arg-type]


def next_allowed_ready(schedule: PostponementSchedule, now: datetime) -> datetime | None:
    """None whenever nothing needs holding back right now: either the
    schedule doesn't restrict anything at all (every day disabled), or `now`
    already falls within today's own allowed window. Otherwise the next
    datetime that would satisfy it.

    For a caller (coordinator.py's own _recompute_all) that already knows
    this entity is otherwise "ready" (its own wait period has fully elapsed)
    and wants to know whether the schedule should hold it back a little
    longer, and until when -- not a general "is this entity ready" check on
    its own.

    A day with no time set (None) means "any time that day" -- the whole day
    counts as allowed, from its own start. A day WITH a time set is a strict,
    exact weekly check-in instead, not a "that time or any time after" open
    window: direct user feedback, 2026-08-11, correcting an earlier version
    of this function that let a wait period finishing at 12:28 on a day set
    for 10:00 count as already allowed. Once that exact instant has passed --
    even moments later, even still the same day -- this occurrence no longer
    applies; the search continues to the next enabled day/occurrence instead,
    which for a single enabled day means a further 7 days out. Checked over
    8 days, not 7 -- a single enabled day whose own instant already passed
    today needs today-plus-7 (next week, same day) to still be found within
    the loop.

    `now` must be timezone-aware (or naive, matching the schedule's own
    stored times) -- same contract staging.py's own evaluate_staging already
    has for `now`/`available_since`, not normalized here either."""
    for offset in range(8):
        day = now + timedelta(days=offset)
        rule = schedule.days[day.weekday()]
        if not rule.enabled:
            continue
        if rule.time is None:
            allowed_from = datetime.combine(day.date(), time.min, tzinfo=now.tzinfo)
            if allowed_from <= now:
                return None
            return allowed_from
        allowed_from = datetime.combine(day.date(), rule.time, tzinfo=now.tzinfo)
        if allowed_from < now:
            continue  # this occurrence already passed -- doesn't count, keep looking
        if allowed_from == now:
            return None
        return allowed_from
    return None  # every day disabled (the default) -- nothing to hold back
