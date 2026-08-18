"""Retention logic for install_log.py's persisted entries: which entries
keep their full release_notes text, and the byte-size backstop that
degrades that policy further if the store still grows too large.

Kept free of any homeassistant import, same reasoning as staging.py/
semver.py -- see tests/test_install_log_retention.py.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, NamedTuple


class RetentionPolicy(NamedTuple):
    fresh_days: int
    per_entity_floor: int


# The normal, always-applied policy: full release_notes for anything within
# 90 days, unioned with each entity's own most recent 2 entries regardless
# of age (2, not 1, so there's always a prior version to compare against
# when troubleshooting a bad update on an entity that rarely updates, not
# just a single snapshot).
DEFAULT_POLICY = RetentionPolicy(fresh_days=90, per_entity_floor=2)

# websocket_api.py's own _handle_install_log default (unpaginated) page --
# a shorter window than DEFAULT_POLICY above, tuned to match the panel's
# own historySections buckets (Today..This month) rather than to how long
# release_notes text is worth keeping on disk. Reuses the same per-entity-
# floor concept for the same reason: a rarely-updating entity's history
# must not be missing on first load just because it's older than 30 days.
DEFAULT_PAGE_POLICY = RetentionPolicy(fresh_days=30, per_entity_floor=2)

# Applied only if DEFAULT_POLICY's own retention still leaves the store over
# max_bytes -- should not trigger in practice (would need one abnormally
# large release_notes blob, or MAX_ENTRIES raised well past its current
# 1000), a backstop rather than the normal operating point.
DEGRADED_POLICIES: tuple[RetentionPolicy, ...] = (
    RetentionPolicy(fresh_days=30, per_entity_floor=1),
    RetentionPolicy(fresh_days=0, per_entity_floor=1),
)


def _parse_installed_at(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def entries_to_keep_full_notes(
    entries: list[dict[str, Any]], policy: RetentionPolicy, now: datetime
) -> set[int]:
    """Indices into `entries` (oldest-first, install_log.py's own order)
    that should keep full release_notes text. Walked newest-first so "most
    recent N per entity" is a running counter, not a second pass per
    entity. `now` must be timezone-aware (or entries' own timestamps must
    be naive too) -- callers are expected to pass HA's own
    dt_util.utcnow(), same contract as staging.py's evaluate_staging."""
    keep: set[int] = set()
    seen_per_entity: dict[str, int] = {}
    for i in range(len(entries) - 1, -1, -1):
        entry = entries[i]
        entity_id = entry.get("entity_id")
        seen = seen_per_entity.get(entity_id, 0)
        if seen < policy.per_entity_floor:
            keep.add(i)
            seen_per_entity[entity_id] = seen + 1
            continue
        installed_at = _parse_installed_at(entry.get("installed_at"))
        if installed_at is not None and now - installed_at < timedelta(days=policy.fresh_days):
            keep.add(i)
    return keep


def apply_release_notes_retention(
    entries: list[dict[str, Any]], policy: RetentionPolicy, now: datetime
) -> None:
    """Mutates `entries` in place: strips release_notes text (sets it to
    None) on every entry not covered by `policy`. Idempotent -- entries
    already stripped are left alone."""
    keep = entries_to_keep_full_notes(entries, policy, now)
    for i, entry in enumerate(entries):
        if i not in keep and entry.get("release_notes") is not None:
            entry["release_notes"] = None


def serialized_size(entries: list[dict[str, Any]]) -> int:
    return len(json.dumps(entries))


def enforce_byte_backstop(
    entries: list[dict[str, Any]], now: datetime, max_bytes: int
) -> None:
    """Only engages if DEFAULT_POLICY's own retention still leaves the
    store over max_bytes: degrades the release-notes policy further first
    (DEGRADED_POLICIES, in order), and only starts dropping the oldest
    entries outright if that's still not enough. Mutates `entries` in
    place."""
    current_size = serialized_size(entries)
    if current_size <= max_bytes:
        return
    for policy in DEGRADED_POLICIES:
        apply_release_notes_retention(entries, policy, now)
        current_size = serialized_size(entries)
        if current_size <= max_bytes:
            return
    # Tracks size as a running estimate (each removed entry's own
    # serialized length, not the whole remaining list's) rather than
    # calling serialized_size(entries) again on every single deletion --
    # that would re-serialize the whole (shrinking, but still large) list
    # once per entry removed, O(n) reserializations of an O(n) list for
    # what only needs to be roughly, not exactly, under max_bytes.
    while len(entries) > 1 and current_size > max_bytes:
        removed = entries.pop(0)
        current_size -= len(json.dumps(removed)) + 1
