"""Tests for the pure, HA-independent vote staleness check."""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "update_manager"

_spec = importlib.util.spec_from_file_location("vote_freshness", _PKG_DIR / "vote_freshness.py")
vote_freshness = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = vote_freshness
_spec.loader.exec_module(vote_freshness)

_NOW = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
_GRACE_PERIOD = timedelta(minutes=5)


class TestIsVoteStale:
    def test_no_voted_at_is_always_stale(self):
        # A pre-2026-08-01 entry, from before voted_at existed at all.
        assert vote_freshness.is_vote_stale(None, _NOW, _GRACE_PERIOD) is True

    def test_just_voted_is_not_stale(self):
        voted_at = (_NOW - timedelta(seconds=5)).isoformat()
        assert vote_freshness.is_vote_stale(voted_at, _NOW, _GRACE_PERIOD) is False

    def test_exactly_at_grace_period_is_not_yet_stale(self):
        voted_at = (_NOW - _GRACE_PERIOD).isoformat()
        assert vote_freshness.is_vote_stale(voted_at, _NOW, _GRACE_PERIOD) is False

    def test_past_grace_period_is_stale(self):
        voted_at = (_NOW - _GRACE_PERIOD - timedelta(seconds=1)).isoformat()
        assert vote_freshness.is_vote_stale(voted_at, _NOW, _GRACE_PERIOD) is True

    def test_parses_a_real_dt_util_utcnow_isoformat_string(self):
        # Confirms the exact shape MyVotesManager.async_remember stores
        # (dt_util.utcnow().isoformat(), a timezone-aware UTC datetime's
        # isoformat -- e.g. "2026-08-01T11:59:00+00:00") parses correctly
        # via plain datetime.fromisoformat, no HA import needed here.
        voted_at = "2026-08-01T11:59:00+00:00"
        assert vote_freshness.is_vote_stale(voted_at, _NOW, _GRACE_PERIOD) is False
