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


def next_allowed_ready(schedule: PostponementSchedule, wait_deadline: datetime) -> datetime | None:
    """None only when the schedule doesn't restrict anything at all (every
    day disabled). Otherwise the schedule-allowed instant this update's own
    wait period (`wait_deadline` -- when its size's own wait_days period
    ends, regardless of whether that's already in the past or still ahead)
    resolves to. May itself be in the past (at or before `wait_deadline`)
    when that deadline already falls inside an allowed window -- the caller
    (coordinator.py's own _apply_schedule_gate) compares this against the
    *actual* current time to decide whether that's already satisfied or
    still ahead, this function only resolves *which* instant matters, not
    whether it's arrived yet.

    Resolved against `wait_deadline` specifically, not against whatever
    moment this happens to be evaluated at (`now`) -- two versions that got
    this wrong were tried and reverted the same day (2026-08-11/12):
    comparing a day's own set time against `now` directly meant the answer
    depended on exactly when coordinator.py's periodic recompute (or the
    precise-wakeup timer) happened to fire, not on anything about the
    update itself -- a wait period that finishes at 12:28 on a day set for
    10:00 got treated as "already allowed" purely because whatever moment
    it happened to be rechecked at was also past 10:00, even though 12:28
    itself is well past that day's own checkpoint and should wait for the
    next one; conversely, requiring an *exact* match against `now` meant
    the ordinary "it's now just past the set time" case almost never
    actually fired, since a periodic check is essentially never at the
    exact instant a schedule's own time ticks over. `wait_deadline` doesn't
    have either problem: it's a fixed fact (available_since + this size's
    own wait_days, see coordinator.py's own _apply_schedule_gate), the same
    value every time this runs for this same update, so the result is
    stable regardless of when it's actually evaluated.

    A day with no time set means "any time that day" -- if `wait_deadline`
    itself already falls on such a day, that's immediately satisfied
    (returns `wait_deadline` itself, not some other instant); a day WITH a
    time set is a strict checkpoint instead: `wait_deadline` on or before it
    satisfies it (returns that exact time), but `wait_deadline` any later
    the same day means this occurrence is missed, keep looking (which, for
    a single enabled day, means a further 7 days out -- checked over 8 days
    for exactly that reason, not 7).

    `wait_deadline` must be timezone-aware (or naive, matching the
    schedule's own stored times) -- same contract staging.py's own
    evaluate_staging already has for `now`/`available_since`, not
    normalized here either."""
    if not any(day.enabled for day in schedule.days):
        return None
    for offset in range(8):
        day = wait_deadline + timedelta(days=offset)
        rule = schedule.days[day.weekday()]
        if not rule.enabled:
            continue
        if rule.time is None:
            start_of_day = datetime.combine(day.date(), time.min, tzinfo=wait_deadline.tzinfo)
            return wait_deadline if start_of_day <= wait_deadline else start_of_day
        allowed_from = datetime.combine(day.date(), rule.time, tzinfo=wait_deadline.tzinfo)
        if allowed_from < wait_deadline:
            continue  # this occurrence's own checkpoint already passed relative to wait_deadline -- doesn't count, keep looking
        return allowed_from
    # Unreachable: the any() check above guarantees at least one enabled
    # weekday within offsets 0-6 (7 consecutive days cover every weekday
    # exactly once); if that occurrence's own checkpoint had already passed
    # (the only way to "continue" past it), offset 7 -- the same weekday, 7
    # days later, so strictly past wait_deadline -- always matches instead.
    # A loud failure here beats a silent, wrong None if that reasoning is
    # ever actually wrong.
    raise AssertionError("next_allowed_ready: no enabled day matched within 8 days despite any(enabled)")
