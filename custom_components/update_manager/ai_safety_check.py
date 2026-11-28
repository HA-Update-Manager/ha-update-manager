"""The actual, HA-dependent half of the AI safety check: fetches this
jump's own release notes/messages (the same get_release_notes service
automations already use, see const.py's own EVENT_ANNOUNCED comment),
builds the instructions via ai_safety_check_prompt.py (kept separate so
tweaking the wording can never change this file's own output contract),
and calls ai_task.generate_data for a block_update/reason verdict.

Always called from a detached background task (see install_manager.py's
own _async_announce), never awaited inline: an ai_task call can take
several seconds, possibly longer with retries, and nothing here may ever
run inside _async_tick's own lock.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Literal, NamedTuple

from homeassistant.core import HomeAssistant

from .ai_safety_check_prompt import build_ai_safety_check_instructions
from .const import DOMAIN, SERVICE_GET_RELEASE_NOTES

_LOGGER = logging.getLogger(__name__)

# Same retry shape as cyclope205/changelog-traduction's own ai_task call
# (3 attempts, 5s/10s between them), the one other real project found this
# session doing the same kind of ai_task-entity classification job.
_RETRY_DELAYS_SECONDS = (5, 10)

AiSafetyCheckStatus = Literal["passed", "blocked", "failed"]
# A "failed" result this module can fully predict/control the shape of
# (not raw, arbitrary ai_task/provider-error text) gets one of these,
# letting the UI show a short, clean, already-translated sentence directly
# (translations.js's own dialog_timeline_ai_check_failed_<code>) instead of
# needing its own info button, direct user feedback, 2026-11-27. None for
# every other case (an ai_task call failing after retries is a raw,
# unpredictable provider error, kept behind the info button same as
# before, see install_manager.py's own comment).
AiSafetyCheckReasonCode = Literal["no_release_notes", "fetch_error"]


class AiSafetyCheckResult(NamedTuple):
    status: AiSafetyCheckStatus
    reason: str | None
    reason_code: AiSafetyCheckReasonCode | None = None
    # Whether reason is worth showing to a person at all, separate from
    # whether it's worth keeping (reason itself is always kept, even when
    # this is False, purely for the debug log, direct user feedback,
    # 2026-11-27: the AI's own routine-pass reason usually just restates
    # the UI's own generic "found no breaking changes" label, not genuinely
    # new information, yet forcing the AI to leave reason itself empty for
    # that case would have thrown away the one thing worth logging for a
    # passed result in the first place). True for "blocked"/every "failed"
    # path (each one is inherently worth showing, see each return site's
    # own comment), the AI's own call only for "passed".
    notable: bool = True


async def async_run_ai_safety_check(
    hass: HomeAssistant,
    *,
    entity_id: str,
    update_name: str,
    from_version: str,
    to_version: str,
    ai_task_entity_id: str,
) -> AiSafetyCheckResult:
    """update_name is already the caller's own cleaned-up friendly name
    (install_manager.py's own _friendly_name, same "Update" suffix strip
    the panel already applies). Not re-derived here, this module has no
    opinion of its own on display names."""
    try:
        notes_result = await hass.services.async_call(
            DOMAIN,
            SERVICE_GET_RELEASE_NOTES,
            {"entity_id": entity_id, "to_version": to_version},
            blocking=True,
            return_response=True,
        )
    except Exception as err:  # noqa: BLE001 (fail-open: any error here just skips the check)
        _LOGGER.debug("AI safety check: get_release_notes failed for %s", entity_id, exc_info=True)
        # reason keeps the real exception for the log above; reason_code
        # is what the UI actually displays (a clean, translated sentence,
        # not this raw, unpredictable exception text).
        return AiSafetyCheckResult("failed", f"Could not fetch the release notes: {err}", "fetch_error")

    notes = (notes_result or {}).get("notes")
    if not notes:
        _LOGGER.debug("AI safety check: no release notes available for %s %s", entity_id, to_version)
        return AiSafetyCheckResult("failed", "No release notes were available for this update.", "no_release_notes")
    messages = (notes_result or {}).get("messages")

    instructions = build_ai_safety_check_instructions(update_name, from_version, to_version, notes, messages=messages)

    last_error: Exception | None = None
    for attempt, delay in enumerate((0, *_RETRY_DELAYS_SECONDS)):
        if delay:
            await asyncio.sleep(delay)
        try:
            result = await hass.services.async_call(
                "ai_task",
                "generate_data",
                {
                    "entity_id": ai_task_entity_id,
                    "task_name": "update_manager_safety_check",
                    "instructions": instructions,
                    "structure": {
                        "block_update": {
                            "selector": {"boolean": {}},
                            "description": "Whether to block this scheduled auto-install.",
                        },
                        "reason": {
                            "selector": {"text": {}},
                            "description": "One short, plain sentence explaining the decision.",
                        },
                        "notable": {
                            "selector": {"boolean": {}},
                            "description": (
                                "Whether reason is worth showing to a person: true if blocking, or if "
                                "there's a detail worth mentioning even though it doesn't block; false "
                                "for a routine pass whose reason is just a restatement of 'no breaking "
                                "changes found'."
                            ),
                        },
                    },
                },
                blocking=True,
                return_response=True,
            )
            data = (result or {}).get("data") or {}
            if "block_update" not in data:
                raise ValueError(f"ai_task.generate_data returned no block_update field: {data!r}")
            reason = data.get("reason")
            # True if the model left this out entirely (shouldn't happen,
            # given the structure declares it, but failing toward "show
            # it" is the safer default than silently hiding a reason that
            # might actually matter).
            notable = bool(data.get("notable", True))
            status: AiSafetyCheckStatus = "blocked" if data["block_update"] else "passed"
            # Logged for every real verdict, not just a failure: direct user
            # feedback, 2026-11-26, a real "passed" result looked
            # questionable against its own release notes, with no way
            # anywhere (not the UI, not the log) to see why the AI decided
            # that. reason itself is always logged here regardless of
            # notable, see AiSafetyCheckResult's own comment for why. The
            # UI's own "why" button (see websocket_api.py's own
            # ai_check_reason) also shows up for "passed"/"blocked", not
            # just this debug line; "blocked" already shows its own reason
            # inline in the timeline ("Cancelled: <reason>"), so the button
            # there is redundant, but this debug line covers it either way.
            _LOGGER.debug("AI safety check: %s %s %s (%s, notable=%s)", entity_id, to_version, status, reason, notable)
            return AiSafetyCheckResult(status, reason, notable=notable)
        except Exception as err:  # noqa: BLE001 (fail-open: retried below, logged once all retries are spent)
            last_error = err

    attempts = len(_RETRY_DELAYS_SECONDS) + 1
    _LOGGER.debug(
        "AI safety check: ai_task.generate_data failed for %s %s after %d attempts: %s",
        entity_id,
        to_version,
        attempts,
        last_error,
    )
    # The real last error, not a generic placeholder. Direct user feedback,
    # 2026-11-26, a real provider outage ("Sorry, I had a problem getting
    # a response from Google Generative AI... 503 UNAVAILABLE") was only
    # visible in an unrelated automation's own log, not here at all, where
    # it actually matters. This is exactly the detail the UI's own "why"
    # button exists to surface for a failed check, same as it already does
    # for a passed one.
    return AiSafetyCheckResult("failed", f"Failed after {attempts} attempts: {last_error}")
