"""Rollout-pacing for a group of devices sharing the same pending update
(e.g. all Zigbee bulbs of the same model): decide which device, if any,
should install next, given how long ago the previous one started.

Kept free of any homeassistant import, same reasoning as semver.py/
staging.py -- see tests/test_rollout.py. Grouping devices by model, actually
triggering `update.install`, and persisting the queue across restarts are
all homeassistant-side concerns layered on top of this, not built yet.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import NamedTuple


class RolloutEntry(NamedTuple):
    device_id: str
    # None = not yet installed. Set once this device's install has been
    # started/completed, so it counts towards pacing the next one.
    installed_at: datetime | None


class RolloutQueue(NamedTuple):
    entries: tuple[RolloutEntry, ...]
    # Minimum time between starting one device's install and the next.
    # Does *not* delay the very first device -- there's nothing to pace
    # against yet.
    wait_between: timedelta


def build_queue(device_ids: list[str], wait_between: timedelta) -> RolloutQueue:
    return RolloutQueue(
        entries=tuple(RolloutEntry(device_id, None) for device_id in device_ids),
        wait_between=wait_between,
    )


def next_ready_device(queue: RolloutQueue, now: datetime) -> str | None:
    """The next device_id that should install now, or None if either
    nothing is left to do, or the pacing interval since the last install
    hasn't elapsed yet."""
    pending = [entry for entry in queue.entries if entry.installed_at is None]
    if not pending:
        return None

    installed_times = [entry.installed_at for entry in queue.entries if entry.installed_at is not None]
    if installed_times:
        last_installed = max(installed_times)
        if now - last_installed < queue.wait_between:
            return None

    # FIFO: whichever pending device was queued first (tuple/list order),
    # not necessarily related to installed_at values.
    return pending[0].device_id


def mark_installed(queue: RolloutQueue, device_id: str, when: datetime) -> RolloutQueue:
    """Returns a new queue with `device_id` marked installed at `when`.
    Raises ValueError if device_id isn't a pending entry in this queue --
    callers are expected to only mark devices next_ready_device actually
    returned, not to call this speculatively."""
    updated: list[RolloutEntry] = []
    found = False
    for entry in queue.entries:
        if entry.device_id == device_id and entry.installed_at is None:
            updated.append(RolloutEntry(entry.device_id, when))
            found = True
        else:
            updated.append(entry)
    if not found:
        raise ValueError(f"{device_id!r} is not a pending entry in this queue")
    return RolloutQueue(entries=tuple(updated), wait_between=queue.wait_between)


def is_complete(queue: RolloutQueue) -> bool:
    return all(entry.installed_at is not None for entry in queue.entries)
