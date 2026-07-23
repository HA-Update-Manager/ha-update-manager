"""Pure, HA-independent construction of a vote issue's body text, split out
from community_vote.py specifically so this stays unit-testable without a
live hass, same reasoning as semver.py/staging.py/hacs_identity.py being
their own dependency-free modules. Worth its own tests: this exact string
format is easy to get subtly wrong (a label typo, a wrong field order) and
hard to catch by reading alone, this session already found two real,
shipped format mismatches on the reading side (release_url's shape, a
missing v-prefix normalization) that a test would have caught immediately.

Field order/labels must match community-votes' own
`.github/ISSUE_TEMPLATE/vote.yml` exactly: that repo's `process-vote.yml`
Action parses the rendered "### Label" shape a real Issue Form submission
produces, not a custom API of its own.
"""
from __future__ import annotations

from typing import Literal

from .hacs_identity import ResolvedIdentity

Verdict = Literal["healthy", "problematic"]

# The real Issue Form's own reason_category dropdown options (verified
# against community-votes' vote.yml, see this module's own docstring),
# minus its "(not applicable, verdict is healthy)" option (never a real
# user choice, always the fixed value build_issue_body substitutes below
# for a healthy vote). websocket_api.py's own `update_manager/vote` command
# validates against this same set server-side (found by review: it used to
# accept any string, which then got written verbatim into a public GitHub
# issue's body as a "### Reason category" field, letting a crafted value
# forge/inject later fields).
REASON_CATEGORIES = (
    "broken functionality",
    "requires a newer HA version",
    "is a dev/pre-release build",
    "breaking change",
    "other",
)


def _field(label: str, value: str | None) -> str:
    return f"### {label}\n\n{value if value else '_No response_'}\n"


def build_issue_body(
    identity: ResolvedIdentity,
    verdict: Verdict,
    reason_category: str | None,
    notes: str | None,
    link: str | None,
) -> str:
    # One field per category (component / owner_repo / manufacturer_model /
    # app_slug) filled in, the rest "_No response_", same as a real Issue
    # Form submission where the other categories' fields were simply never
    # shown/touched. "Manufacturer/model" is a single field, already in
    # "manufacturer/model" format on ResolvedIdentity itself (verified
    # against community-votes' own vote.yml).
    return "\n".join(
        [
            _field("Category", identity.category),
            _field("Component", identity.component),
            _field("Owner/repo", identity.owner_repo),
            _field("Manufacturer/model", identity.manufacturer_model),
            _field("App slug", identity.app_slug),
            _field("Version", identity.version),
            _field("Verdict", verdict),
            _field(
                "Reason category",
                reason_category if verdict == "problematic" else "(not applicable, verdict is healthy)",
            ),
            _field("Notes", notes),
            _field("Issue or changelog link", link),
        ]
    )
