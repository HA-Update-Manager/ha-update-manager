"""Pure grouping logic shared by every one of the 5 per-status sensors in
sensor.py -- mirrors the panel JS's own groupUpdates() (update-manager-
panel.js), so the backend sensors and the Updates tab's own section
headings always agree on what counts as what. Kept pure (plain dicts in,
plain dicts out, no hass) so it's directly unit-testable, same convention
as staging.py/semver.py elsewhere in this project.
"""
from __future__ import annotations

from typing import Any

# Order matters for STATUS_SENSORS in sensor.py (iterated to build entities
# in a stable order) but not for this function itself.
STATUSES = ("ready", "waiting", "blocked", "skipped", "not_installable")


def categorize_updates(updates: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Buckets `updates` (coordinator.cache.values(), or anything with the
    same "status"/"installable" shape) into the same 5 groups the Updates
    tab shows as its own sections, in the same order of precedence.

    installable is checked first, before status, for the exact same reason
    groupUpdates() checks it first in the panel JS: an update that's both
    skipped and not installable counts ONLY as "not_installable", never
    "skipped" -- a real user-initiated skip on something that can't
    actually be installed isn't a meaningful "skipped" in the sense this
    grouping means (mirrors HA's own real Updates page,
    ha-config-section-updates.ts's own _filterSkippedUpdateEntities, which
    additionally requires UpdateEntityFeature.INSTALL for its own "Skipped"
    section the same way)."""
    not_installable = [u for u in updates if not u.get("installable")]
    rest = [u for u in updates if u.get("installable")]
    skipped = [u for u in rest if u.get("status") == "skipped"]
    remaining = [u for u in rest if u.get("status") != "skipped"]
    return {
        "ready": [u for u in remaining if u.get("status") == "ready"],
        "waiting": [u for u in remaining if u.get("status") == "waiting"],
        "blocked": [u for u in remaining if u.get("status") == "blocked"],
        "skipped": skipped,
        "not_installable": not_installable,
    }


# icons.json's own "state" key only matches an exact string (confirmed
# against developers.home-assistant.io's own icon-translations docs -- no
# numeric/range syntax exists there), no use for a plain count. These two
# statuses are the only ones with a real "should this catch your eye or
# not" question worth answering at a glance (Discouraged/Not installable
# both mean "something needs a decision"; Ready/Postponed/Skipped are just
# neutral facts, a count of zero isn't more or less noteworthy there than
# any other count), so only these two get a genuinely dynamic icon.
# icons.json's own entries stay in place as the real translated defaults
# (still used by anything reading icon-translations directly, and as the
# "count > 0" case below, kept in sync by hand since icons.json can't be
# read from Python).
_CALM_ICONS = {
    "blocked": "mdi:shield-check-outline",
    "not_installable": "mdi:check-circle-outline",
}


def icon_for_status(status: str, count: int) -> str | None:
    """None means "use icons.json's own translated default" -- sensor.py's
    own icon property returns this straight through, HA's documented way to
    go beyond a static icons.json entry for the one case (a genuinely
    dynamic, count-based choice) icons.json itself can't express."""
    calm_icon = _CALM_ICONS.get(status)
    if calm_icon is not None and count == 0:
        return calm_icon
    return None
