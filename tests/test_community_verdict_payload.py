"""Tests for the pure, HA-independent to_version-payload extraction."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "update_manager"

_spec = importlib.util.spec_from_file_location(
    "community_verdict_payload", _PKG_DIR / "community_verdict_payload.py"
)
community_verdict_payload = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = community_verdict_payload
_spec.loader.exec_module(community_verdict_payload)


def _payload(**jumps):
    return {"jumps": jumps}


class TestVerdictFromPayload:
    def test_returns_my_jumps_verdict(self):
        payload = _payload(**{"3.5.1": {"votes": {}, "verdict": {"healthy_count": 2, "problematic_count": 0}}})
        assert community_verdict_payload.verdict_from_payload(payload, "3.5.1") == {
            "healthy_count": 2,
            "problematic_count": 0,
        }

    def test_none_when_jump_not_rated_at_all(self):
        payload = _payload(**{"3.5.1": {"votes": {}, "verdict": {"healthy_count": 1, "problematic_count": 0}}})
        assert community_verdict_payload.verdict_from_payload(payload, "0.1.0") is None

    def test_none_when_payload_itself_is_none(self):
        assert community_verdict_payload.verdict_from_payload(None, "3.5.1") is None


class TestMyVoteFromPayload:
    def test_returns_specific_users_own_verdict(self):
        payload = _payload(
            **{
                "3.5.1": {
                    "votes": {"klaptafel": {"verdict": "healthy"}, "alice": {"verdict": "problematic"}},
                    "verdict": {"healthy_count": 1, "problematic_count": 1},
                }
            }
        )
        assert community_verdict_payload.my_vote_from_payload(payload, "3.5.1", "klaptafel") == "healthy"
        assert community_verdict_payload.my_vote_from_payload(payload, "3.5.1", "alice") == "problematic"

    def test_none_when_username_never_voted_on_this_jump(self):
        payload = _payload(**{"3.5.1": {"votes": {"klaptafel": {"verdict": "healthy"}}, "verdict": {}}})
        assert community_verdict_payload.my_vote_from_payload(payload, "3.5.1", "bob") is None

    def test_none_when_username_voted_on_a_different_jump_only(self):
        # Confirms a vote is genuinely scoped to one exact jump, not the
        # destination version as a whole -- someone who voted on the 0.1.0
        # jump must not appear to have voted on the 3.5.1 jump too.
        payload = _payload(
            **{
                "0.1.0": {"votes": {"klaptafel": {"verdict": "healthy"}}, "verdict": {}},
                "3.5.1": {"votes": {}, "verdict": {}},
            }
        )
        assert community_verdict_payload.my_vote_from_payload(payload, "3.5.1", "klaptafel") is None


class TestTrustedVoteFromPayload:
    def test_no_trusted_voters_configured_short_circuits(self):
        payload = _payload(**{"3.5.1": {"votes": {"klaptafel": {"verdict": "problematic"}}, "verdict": {}}})
        assert community_verdict_payload.trusted_vote_from_payload(payload, "3.5.1", []) == (None, [])

    def test_single_trusted_voter_healthy(self):
        payload = _payload(**{"3.5.1": {"votes": {"klaptafel": {"verdict": "healthy"}}, "verdict": {}}})
        assert community_verdict_payload.trusted_vote_from_payload(payload, "3.5.1", ["klaptafel"]) == (
            "healthy",
            ["klaptafel"],
        )

    def test_single_trusted_voter_problematic(self):
        payload = _payload(**{"3.5.1": {"votes": {"klaptafel": {"verdict": "problematic"}}, "verdict": {}}})
        assert community_verdict_payload.trusted_vote_from_payload(payload, "3.5.1", ["klaptafel"]) == (
            "problematic",
            ["klaptafel"],
        )

    def test_any_problematic_wins_even_if_others_voted_healthy(self):
        # Same asymmetric-safety rule as the aggregate auto-install quorum
        # (FUTURE.md's own point 5): one problematic vote among the trusted
        # list blocks outright, regardless of how many others voted healthy.
        payload = _payload(
            **{
                "3.5.1": {
                    "votes": {
                        "alice": {"verdict": "healthy"},
                        "bob": {"verdict": "problematic"},
                        "carol": {"verdict": "healthy"},
                    },
                    "verdict": {},
                }
            }
        )
        verdict, matched = community_verdict_payload.trusted_vote_from_payload(
            payload, "3.5.1", ["alice", "bob", "carol"]
        )
        assert verdict == "problematic"
        assert matched == ["bob"]

    def test_healthy_only_when_none_of_the_trusted_voters_are_problematic(self):
        payload = _payload(
            **{
                "3.5.1": {
                    "votes": {"alice": {"verdict": "healthy"}, "carol": {"verdict": "healthy"}},
                    "verdict": {},
                }
            }
        )
        verdict, matched = community_verdict_payload.trusted_vote_from_payload(payload, "3.5.1", ["alice", "carol"])
        assert verdict == "healthy"
        assert set(matched) == {"alice", "carol"}

    def test_trusted_voter_who_never_voted_on_this_jump_is_ignored(self):
        payload = _payload(**{"3.5.1": {"votes": {"alice": {"verdict": "healthy"}}, "verdict": {}}})
        assert community_verdict_payload.trusted_vote_from_payload(payload, "3.5.1", ["dave"]) == (None, [])

    def test_trusted_vote_scoped_to_my_own_jump_not_a_different_one(self):
        # A trusted username's vote on a *different* from_version landing on
        # the same destination must not override my own, different jump.
        payload = _payload(
            **{
                "0.1.0": {"votes": {"klaptafel": {"verdict": "healthy"}}, "verdict": {}},
                "3.5.1": {"votes": {}, "verdict": {}},
            }
        )
        assert community_verdict_payload.trusted_vote_from_payload(payload, "3.5.1", ["klaptafel"]) == (None, [])


class TestOtherJumpsFromPayload:
    def test_excludes_my_own_jump(self):
        payload = _payload(
            **{
                "3.5.1": {"votes": {}, "verdict": {"healthy_count": 5, "problematic_count": 0}},
                "0.1.0": {"votes": {}, "verdict": {"healthy_count": 1, "problematic_count": 0}},
            }
        )
        others = community_verdict_payload.other_jumps_from_payload(payload, "3.5.1")
        assert [j["from_version"] for j in others] == ["0.1.0"]

    def test_empty_when_no_other_jumps_exist(self):
        payload = _payload(**{"3.5.1": {"votes": {}, "verdict": {"healthy_count": 5, "problematic_count": 0}}})
        assert community_verdict_payload.other_jumps_from_payload(payload, "3.5.1") == []

    def test_empty_when_payload_is_none(self):
        assert community_verdict_payload.other_jumps_from_payload(None, "3.5.1") == []

    def test_skips_a_jump_with_no_verdict_yet(self):
        payload = _payload(**{"3.5.1": {"votes": {}, "verdict": None}})
        assert community_verdict_payload.other_jumps_from_payload(payload, "0.1.0") == []

    def test_sorted_by_total_votes_descending(self):
        payload = _payload(
            **{
                "current": {"votes": {}, "verdict": {"healthy_count": 0, "problematic_count": 0}},
                "0.1.0": {"votes": {}, "verdict": {"healthy_count": 1, "problematic_count": 0}},
                "2.0.0": {"votes": {}, "verdict": {"healthy_count": 3, "problematic_count": 1}},
                "1.0.0": {"votes": {}, "verdict": {"healthy_count": 2, "problematic_count": 0}},
            }
        )
        others = community_verdict_payload.other_jumps_from_payload(payload, "current")
        assert [j["from_version"] for j in others] == ["2.0.0", "1.0.0", "0.1.0"]

    def test_capped_at_max_other_jumps(self):
        jumps = {
            f"1.0.{i}": {"votes": {}, "verdict": {"healthy_count": i, "problematic_count": 0}} for i in range(10)
        }
        payload = _payload(**jumps)
        others = community_verdict_payload.other_jumps_from_payload(payload, "nonexistent")
        assert len(others) == community_verdict_payload.MAX_OTHER_JUMPS
        # Highest counts kept, not an arbitrary/first-N slice.
        assert [j["from_version"] for j in others] == ["1.0.9", "1.0.8", "1.0.7", "1.0.6", "1.0.5"]

    def test_returned_shape_has_only_the_documented_fields(self):
        payload = _payload(
            **{
                "3.5.1": {"votes": {}, "verdict": {}},
                "0.1.0": {
                    "votes": {},
                    "verdict": {
                        "healthy_count": 1,
                        "problematic_count": 0,
                        "quorum": 3,
                        "quorum_reached": False,
                        "auto_install_eligible": False,
                        "updated_at": "2026-07-24T00:00:00+00:00",
                    },
                },
            }
        )
        others = community_verdict_payload.other_jumps_from_payload(payload, "3.5.1")
        assert others == [
            {
                "from_version": "0.1.0",
                "healthy_count": 1,
                "problematic_count": 0,
                "quorum_reached": False,
                "auto_install_eligible": False,
            }
        ]


class TestProblematicReasonsFromPayload:
    def test_empty_when_payload_is_none(self):
        assert community_verdict_payload.problematic_reasons_from_payload(None, "3.5.1") == []

    def test_empty_when_no_problematic_votes_on_this_jump(self):
        payload = _payload(**{"3.5.1": {"votes": {"alice": {"verdict": "healthy"}}, "verdict": {}}})
        assert community_verdict_payload.problematic_reasons_from_payload(payload, "3.5.1") == []

    def test_healthy_votes_are_excluded_even_though_reason_category_is_none(self):
        # A healthy vote never carries a reason (vote_issue_body.py only
        # renders one for a problematic verdict), so reason_category is
        # always None for these -- must not be mistaken for "an
        # unspecified problematic reason" and included anyway.
        payload = _payload(
            **{"3.5.1": {"votes": {"alice": {"verdict": "healthy", "reason_category": None}}, "verdict": {}}}
        )
        assert community_verdict_payload.problematic_reasons_from_payload(payload, "3.5.1") == []

    def test_returns_reason_fields_for_a_problematic_vote(self):
        payload = _payload(
            **{
                "3.5.1": {
                    "votes": {
                        "alice": {
                            "verdict": "problematic",
                            "reason_category": "breaking change",
                            "notes": "Broke my dashboard",
                            "link": "https://github.com/example/example/issues/1",
                            "created_at": "2026-07-20T00:00:00+00:00",
                        }
                    },
                    "verdict": {},
                }
            }
        )
        assert community_verdict_payload.problematic_reasons_from_payload(payload, "3.5.1") == [
            {
                "username": "alice",
                "reason_category": "breaking change",
                "notes": "Broke my dashboard",
                "link": "https://github.com/example/example/issues/1",
                "created_at": "2026-07-20T00:00:00+00:00",
            }
        ]

    def test_scoped_to_my_own_jump_not_a_different_one(self):
        payload = _payload(
            **{
                "0.1.0": {"votes": {"alice": {"verdict": "problematic", "reason_category": "other"}}, "verdict": {}},
                "3.5.1": {"votes": {}, "verdict": {}},
            }
        )
        assert community_verdict_payload.problematic_reasons_from_payload(payload, "3.5.1") == []

    def test_sorted_most_recent_first(self):
        payload = _payload(
            **{
                "3.5.1": {
                    "votes": {
                        "alice": {"verdict": "problematic", "created_at": "2026-07-10T00:00:00+00:00"},
                        "bob": {"verdict": "problematic", "created_at": "2026-07-25T00:00:00+00:00"},
                        "carol": {"verdict": "problematic", "created_at": "2026-07-15T00:00:00+00:00"},
                    },
                    "verdict": {},
                }
            }
        )
        reasons = community_verdict_payload.problematic_reasons_from_payload(payload, "3.5.1")
        assert [r["username"] for r in reasons] == ["bob", "carol", "alice"]

    def test_capped_at_max_problematic_reasons(self):
        votes = {
            f"voter{i}": {"verdict": "problematic", "created_at": f"2026-07-{i + 1:02d}T00:00:00+00:00"}
            for i in range(10)
        }
        payload = _payload(**{"3.5.1": {"votes": votes, "verdict": {}}})
        reasons = community_verdict_payload.problematic_reasons_from_payload(payload, "3.5.1")
        assert len(reasons) == community_verdict_payload.MAX_PROBLEMATIC_REASONS
        # Most recent kept, not an arbitrary/first-N slice.
        assert [r["username"] for r in reasons] == ["voter9", "voter8", "voter7", "voter6", "voter5"]

    def test_exclude_username_filters_before_capping_not_after(self):
        # Found by review, 2026-07-29: excluding a username from an
        # already-capped result could silently lose it if it wasn't
        # already in the top MAX_PROBLEMATIC_REASONS -- exclude_username
        # must remove it *before* the cap, so the cap always keeps
        # MAX_PROBLEMATIC_REASONS genuinely-other reasons, not one fewer.
        votes = {
            f"voter{i}": {"verdict": "problematic", "created_at": f"2026-07-{i + 1:02d}T00:00:00+00:00"}
            for i in range(10)
        }
        # "me" is the single most recent vote -- if exclusion happened
        # after capping, this test would still pass by accident (it'd
        # never have been in the top 5 anyway); the real assertion is that
        # the cap still yields a full 5 *other* people, not 4.
        votes["me"] = {"verdict": "problematic", "created_at": "2026-07-11T00:00:00+00:00"}
        payload = _payload(**{"3.5.1": {"votes": votes, "verdict": {}}})
        reasons = community_verdict_payload.problematic_reasons_from_payload(
            payload, "3.5.1", exclude_username="me"
        )
        assert len(reasons) == community_verdict_payload.MAX_PROBLEMATIC_REASONS
        assert "me" not in [r["username"] for r in reasons]

    def test_exclude_username_none_keeps_everyone(self):
        payload = _payload(**{"3.5.1": {"votes": {"alice": {"verdict": "problematic"}}, "verdict": {}}})
        reasons = community_verdict_payload.problematic_reasons_from_payload(payload, "3.5.1", exclude_username=None)
        assert [r["username"] for r in reasons] == ["alice"]


class TestMyProblematicReasonFromPayload:
    def test_none_when_payload_is_none(self):
        assert community_verdict_payload.my_problematic_reason_from_payload(None, "3.5.1", "alice") is None

    def test_none_when_username_is_none(self):
        payload = _payload(**{"3.5.1": {"votes": {"alice": {"verdict": "problematic"}}, "verdict": {}}})
        assert community_verdict_payload.my_problematic_reason_from_payload(payload, "3.5.1", None) is None

    def test_none_when_username_never_voted(self):
        payload = _payload(**{"3.5.1": {"votes": {"alice": {"verdict": "problematic"}}, "verdict": {}}})
        assert community_verdict_payload.my_problematic_reason_from_payload(payload, "3.5.1", "bob") is None

    def test_none_when_username_voted_healthy_not_problematic(self):
        payload = _payload(**{"3.5.1": {"votes": {"alice": {"verdict": "healthy"}}, "verdict": {}}})
        assert community_verdict_payload.my_problematic_reason_from_payload(payload, "3.5.1", "alice") is None

    def test_returns_reason_regardless_of_how_many_others_voted_more_recently(self):
        # The exact scenario the capped list would get wrong: 5 other
        # people voted problematic more recently than "me" -- a search
        # over problematic_reasons_from_payload's own capped top-5 would
        # never find "me" here, but this direct lookup still does.
        votes = {
            f"voter{i}": {"verdict": "problematic", "created_at": f"2026-07-{i + 20:02d}T00:00:00+00:00"}
            for i in range(5)
        }
        votes["me"] = {
            "verdict": "problematic",
            "reason_category": "breaking change",
            "notes": "my own notes",
            "link": None,
            "created_at": "2026-07-01T00:00:00+00:00",
        }
        payload = _payload(**{"3.5.1": {"votes": votes, "verdict": {}}})
        assert community_verdict_payload.my_problematic_reason_from_payload(payload, "3.5.1", "me") == {
            "username": "me",
            "reason_category": "breaking change",
            "notes": "my own notes",
            "link": None,
            "created_at": "2026-07-01T00:00:00+00:00",
        }
