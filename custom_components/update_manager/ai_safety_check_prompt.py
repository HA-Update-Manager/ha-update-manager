"""Pure, HA-independent construction of the AI safety check's own
instructions text for ai_task.generate_data, same split-out reasoning as
vote_issue_body.py/firmware_version_issue_body.py: this exact wording is
easy to get subtly wrong and hard to catch by reading alone, and kept in
its own file specifically so it stays easy to tweak via its own, focused
pull request without ever touching the surrounding call/structured-output
logic. The expected output shape (block_update/reason) is deliberately
NOT defined here at all, only described in prose for the model to follow;
the real probatio/selector schema that actually enforces that shape lives
wherever this gets called from instead, so a wording tweak here can never
accidentally change what a caller expects back.

Based on two real, already-working implementations, not invented from
scratch: the direct inspiration is the project maintainer's own home-grown
Home Assistant automation ("Update Manager - AI Safety Check", already in
daily use, direct user feedback: "werkt vrij aardig"), cross-checked
against a separate, unrelated HACS integration doing a similar classification
job for a different purpose (cyclope205/changelog-traduction, which asks an
ai_task entity to judge release notes for its own "only notify on a
breaking change" alert mode, not an auto-install decision)."""
from __future__ import annotations


def build_ai_safety_check_instructions(
    update_name: str,
    from_version: str,
    to_version: str,
    release_text: str,
    messages: list[dict[str, str]] | None = None,
) -> str:
    """release_text is whatever the caller already has in hand (the same
    compiled, trimmed-to-this-jump text the dialog/get_release_notes action
    show, covering every version in between for a multi-version jump, not
    just the latest one). Never fetched or validated here, this module
    has no I/O of its own at all. Callers already decide not to call this
    (or the AI) at all when release_text would be empty (see the fail-open
    paths this feature is built around), so this doesn't special-case that
    itself.

    messages is release_notes_messages, HA Core 2026.12's own per-update
    warning/info/error the update entity's own integration can attach
    directly (see coordinator.py's own docstring on _fetchNativeReleaseNotes
    for the feature itself). Included as its own, clearly separate
    section when present, since these come straight from the integration's
    own code, not its prose changelog, and deserve at least as much weight."""
    messages_section = ""
    if messages:
        lines = "\n".join(f"- [{message['severity']}] {message['message']}" for message in messages)
        messages_section = (
            "\n\nThe update's own integration also attached these warnings directly (not just "
            "release-note prose, these come from the integration's own code, so treat them as at "
            f"least as reliable as the text below):\n{lines}\n"
        )

    return (
        "Review the release notes below for a scheduled automatic Home Assistant update, and decide "
        "whether a person should review it manually before it installs, rather than letting it install "
        "automatically as planned.\n\n"
        f"Update: {update_name}\n"
        f"Version change: {from_version} -> {to_version}\n\n"
        "Set block_update=true ONLY if the text below describes a concrete reason why manual review is "
        "needed before this exact jump installs. This includes, specifically:\n"
        "- An explicitly stated breaking change (renamed or removed entities, services, or configuration keys)\n"
        "- A required manual migration or configuration change\n"
        "- A known serious bug, regression, or incompatibility\n"
        "- A real risk of data loss, a broken startup, or lost functionality\n"
        "- Any other change the text itself says needs human action before or right after installing\n\n"
        "New features, ordinary bug fixes, performance improvements, general or vague cautionary "
        "language, and anything not actually stated in the text below are NOT sufficient to block the "
        "update on their own.\n\n"
        "The release notes may cover more than one release at once (a multi-version jump, already "
        "compiled together): treat a concrete reason found anywhere in it the same way, regardless of "
        "which specific version within the jump it belongs to.\n\n"
        "Do not speculate beyond what the text actually says, and do not invent a reason that isn't "
        "there. If the available information is missing, unclear, or not enough for a confident "
        "decision, set block_update=false.\n\n"
        "reason must be one short, plain sentence, not a paragraph: if blocking, state the concrete "
        'reason found; if not blocking, say so briefly (e.g. "No breaking changes found in the release '
        'notes."). Always fill this in, even for a routine pass with nothing further to add: it\'s kept '
        "for diagnostic purposes regardless of whether anything displays it.\n\n"
        "notable must be true if blocking, or if there's something worth mentioning in reason even "
        "though it doesn't rise to blocking (a minor behavior change, a deprecation notice, something "
        "worth keeping an eye on); false for a routine pass whose reason is just a restatement of "
        '"nothing concrete was found", with nothing more specific to add.'
        f"{messages_section}\n"
        "RELEASE NOTES:\n\n"
        f"{release_text}"
    )
