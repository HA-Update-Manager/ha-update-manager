"""Pure, HA-independent construction of a vote issue's body text, split out
from community_vote.py specifically so this stays unit-testable without a
live hass, same reasoning as semver.py/staging.py/hacs_identity.py being
their own dependency-free modules. Worth its own tests: this exact string
format is easy to get subtly wrong (a label typo, a wrong field order) and
hard to catch by reading alone, this session already found two real,
shipped format mismatches on the reading side (release_url's shape, a
missing v-prefix normalization) that a test would have caught immediately.

Field labels must match community-votes' own `.github/ISSUE_TEMPLATE/vote.yml`
exactly for every field that Action's own process-vote.yml actually reads
back out by name (Category, Component, Owner/repo, Manufacturer/model, App
slug, From/To version, Verdict, Reason category, Notes, Issue or changelog
link): that script parses the rendered "### Label" shape a real Issue Form
submission produces, not a custom API of its own. "Release" is the one
exception, added 2026-08-01 with no vote.yml counterpart at all -- see
build_issue_body's own comment for why that's safe. Order itself doesn't
matter to parsing (process-vote.yml builds a label -> value dict, not a
positional read), only human readability of the rendered issue.
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
    #
    # "Release" (added 2026-08-01) is the one field here with no counterpart
    # in community-votes' own vote.yml, safe to add anyway -- verified
    # directly against that repo's own process-vote.yml: parseFields()
    # captures every "### Label" block it finds into a plain object with no
    # fixed schema, and the rest of the script only ever reads specific
    # known keys (Category, Owner/repo, etc.) back out of it, so an unknown
    # extra key just sits there unread, never rejected or misparsed.
    # Deliberately not folded into "Owner/repo" itself, though: that field's
    # own value *is* structurally used (that Action's hacs branch does
    # `ownerRepo.split("/")` and rejects the whole vote unless that's
    # exactly 2 parts), same for "To version" (used verbatim to build the
    # per-version storage path/issue title) -- a markdown link or an
    # appended URL in either would break real, load-bearing parsing, not
    # just sit there unused like this new field does.
    return "\n".join(
        [
            _field("Category", identity.category),
            _field("Component", identity.component),
            _field("Owner/repo", identity.owner_repo),
            _field("Manufacturer/model", identity.manufacturer_model),
            _field("App slug", identity.app_slug),
            _field("From version", identity.from_version),
            _field("To version", identity.to_version),
            _field("Release", identity.release_url),
            _field("Verdict", verdict),
            _field(
                "Reason category",
                reason_category if verdict == "problematic" else "(not applicable, verdict is healthy)",
            ),
            _field("Notes", notes),
            _field("Issue or changelog link", link),
        ]
    )
