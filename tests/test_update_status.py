"""Tests for the pure, HA-independent update-status grouping logic."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_MODULE_PATH = (
    Path(__file__).resolve().parent.parent
    / "custom_components" / "update_manager" / "update_status.py"
)
_spec = importlib.util.spec_from_file_location("update_manager_update_status", _MODULE_PATH)
update_status = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(update_status)


def _u(status, installable=True, **extra):
    return {"status": status, "installable": installable, **extra}


class TestCategorizeUpdates:
    def test_buckets_by_status(self):
        updates = [_u("ready"), _u("waiting"), _u("blocked")]
        result = update_status.categorize_updates(updates)
        assert result["ready"] == [updates[0]]
        assert result["waiting"] == [updates[1]]
        assert result["blocked"] == [updates[2]]
        assert result["skipped"] == []
        assert result["not_installable"] == []

    def test_skipped_and_installable_counts_as_skipped(self):
        u = _u("skipped", installable=True)
        result = update_status.categorize_updates([u])
        assert result["skipped"] == [u]
        assert result["not_installable"] == []

    def test_skipped_but_not_installable_counts_only_as_not_installable(self):
        """Mirrors groupUpdates()'s own precedence in the panel JS: a real
        user-initiated skip on something that can't actually be installed
        isn't a meaningful "skipped" in the sense this grouping means."""
        u = _u("skipped", installable=False)
        result = update_status.categorize_updates([u])
        assert result["not_installable"] == [u]
        assert result["skipped"] == []

    def test_not_installable_regardless_of_status(self):
        updates = [_u("ready", installable=False), _u("waiting", installable=False)]
        result = update_status.categorize_updates(updates)
        assert result["not_installable"] == updates
        assert result["ready"] == []
        assert result["waiting"] == []

    def test_empty_input_returns_all_empty_buckets(self):
        result = update_status.categorize_updates([])
        assert result == {"ready": [], "waiting": [], "blocked": [], "skipped": [], "not_installable": []}

    def test_unknown_status_is_dropped_silently(self):
        """A status this grouping doesn't recognize (shouldn't happen given
        staging.py's own Literal type, but this function takes plain dicts,
        not that type) simply doesn't land in any bucket, rather than
        raising -- same "never crash the sensor over unexpected data"
        principle every other coordinator-reading part of this project
        already follows."""
        result = update_status.categorize_updates([_u("installing")])
        assert sum(len(v) for v in result.values()) == 0


class TestIconForStatus:
    def test_blocked_shows_calm_icon_when_empty(self):
        assert update_status.icon_for_status("blocked", 0) == "mdi:shield-check-outline"

    def test_blocked_falls_back_to_default_when_nonempty(self):
        assert update_status.icon_for_status("blocked", 1) is None
        assert update_status.icon_for_status("blocked", 5) is None

    def test_not_installable_shows_calm_icon_when_empty(self):
        assert update_status.icon_for_status("not_installable", 0) == "mdi:check-circle-outline"

    def test_not_installable_falls_back_to_default_when_nonempty(self):
        assert update_status.icon_for_status("not_installable", 3) is None

    def test_neutral_statuses_never_get_a_calm_icon(self):
        """ready/waiting/skipped have no "should this catch your eye"
        connotation -- a count of zero there isn't more noteworthy than any
        other count, so these always fall back to icons.json's own default,
        empty or not."""
        for status in ("ready", "waiting", "skipped"):
            assert update_status.icon_for_status(status, 0) is None
            assert update_status.icon_for_status(status, 4) is None
