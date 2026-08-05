"""Exposes Update Manager's computed state over HA's websocket API. This,
not the summary sensor, is the intended data source for Phase 2's panel
(see FUTURE.md) -- the sensor stays around as a cheap debug view, but a
growing update list / install history doesn't belong in an entity's state
machine footprint.

Also the panel's only way to change the staging rules: a config_entry's
options can't be written from a plain custom element, so save_settings
mutates it the same way the (now superseded) options flow did, going
through hass.config_entries.async_update_entry so the existing
update_listener/reload picks up the new rules exactly as before.

Single-instance integration (config_flow enforces this), so there is at
most one entry/coordinator/install log/install manager to read from at a
time.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_ANNOUNCE_HOURS,
    CONF_ENABLED,
    CONF_EXCLUDED_ENTITIES,
    CONF_HIDE_POSTPONED,
    CONF_LARGE_AUTO_INSTALL,
    CONF_LARGE_WAIT_DAYS,
    CONF_MEDIUM_AUTO_INSTALL,
    CONF_MEDIUM_WAIT_DAYS,
    CONF_SMALL_AUTO_INSTALL,
    CONF_SMALL_WAIT_DAYS,
    CONF_TRUSTED_VOTERS,
    DEFAULT_WAIT_DAYS,
    DOMAIN,
)
from .community_verdict import (
    EMPTY_VERDICT_RESULT,
    async_fetch_my_vote,
    async_fetch_verdict_uncached,
    async_fetch_vote_for_jump_key,
)
from .community_vote import async_submit_vote
from .coordinator import (
    excluded_entities_from_options,
    hard_excluded_entity_ids,
    rules_from_options,
    trusted_voters_from_options,
)
from .device_identity import resolve_full_identity
from .github_release_notes import compile_release_range, find_release_by_version, parse_release_url
from .hacs_identity import ResolvedIdentity
from .install_manager import auto_install_rules_from_options
from .runtime_data import UpdateManagerConfigEntry, UpdateManagerData
from .vote_issue_body import REASON_CATEGORIES

_WS_REGISTERED = f"{DOMAIN}_ws_registered"

# How long a remembered vote (my_votes.py) is trusted unconditionally before
# _handle_verdict_for_version starts cross-checking it against live
# community-votes data at all -- comfortably longer than community-votes'
# own process-vote.yml Action typically takes to process a freshly opened
# vote issue (seconds), short enough that a genuinely externally-deleted
# vote still self-heals within one reasonable dialog-reopen. See
# MyVotesManager.is_stale's own docstring for the full reasoning.
_STALE_VOTE_GRACE_PERIOD = timedelta(minutes=5)


def _get_entry(hass: HomeAssistant) -> UpdateManagerConfigEntry | None:
    """The one entry this single-instance integration ever has (config_flow
    enforces this, see this module's own docstring), or None before setup
    has run. The single place every websocket handler below (none of which
    receive a ConfigEntry of their own the way a platform's async_setup_entry
    does) resolves it from -- found by review while migrating off
    hass.data[DOMAIN] to entry.runtime_data: _handle_get_settings and
    _handle_save_settings already looked this entry up by hand, duplicating
    the same hass.config_entries.async_entries(DOMAIN) call every other
    handler below now also needs."""
    entries = hass.config_entries.async_entries(DOMAIN)
    return entries[0] if entries else None


def _get_data(hass: HomeAssistant) -> UpdateManagerData | None:
    """entry.runtime_data for the one entry above, or None before setup has
    run -- runtime_data itself defaults to None until async_setup_entry
    assigns it, so this already reads exactly like the old
    hass.data.get(DOMAIN) it replaces, no extra None-check needed here."""
    entry = _get_entry(hass)
    return entry.runtime_data if entry else None


async def async_apply_options(hass: HomeAssistant, options: dict) -> None:
    """Applies newly-saved settings to every manager in place, no reload
    needed -- shared by _handle_save_settings below (awaited directly, so
    the panel's own post-save reload sees fresh data) and __init__.py's
    update_listener (HA's own config-entry update mechanism, fired as an
    unawaited background task shortly after -- a harmless, idempotent
    re-application of the same already-applied state). Found by review:
    the two used to duplicate this exact sequence by hand, needing every
    future setting/manager added here to be edited in both places."""
    data = _get_data(hass)
    if not data:
        return
    master_enabled = bool(options.get(CONF_ENABLED, True))
    # coordinator's own rules recompute goes first -- both managers below
    # read its freshly-recomputed cache. From there, install_manager and
    # staging_skip_manager are fully independent of each other (different
    # managers, don't touch each other's state), so they're gathered
    # concurrently instead of awaited one after the other -- found live:
    # a settings save awaits install_manager's own tick (now potentially
    # over every tracked entity, see install_manager.py's own async_start)
    # and staging_skip_manager's two calls one after another, so the panel's
    # Save button spun for roughly the *sum* of both instead of the max.
    # staging_skip_manager's own two calls stay sequential relative to each
    # other (both act on the same self._skipped dict via the same lock, so
    # gathering them wouldn't add real concurrency, only reorder which one
    # "wins" the lock first).
    await data.coordinator.async_update_rules(
        rules_from_options(options), excluded_entities_from_options(options)
    )
    data.install_manager.update_rules(auto_install_rules_from_options(options))
    data.community_verdict_manager.set_trusted_voters(trusted_voters_from_options(options))

    async def _apply_staging_skip() -> None:
        await data.staging_skip_manager.async_update_enabled(options.get(CONF_HIDE_POSTPONED, True))
        await data.staging_skip_manager.async_set_master_enabled(master_enabled)

    await asyncio.gather(
        data.install_manager.async_set_master_enabled(master_enabled),
        _apply_staging_skip(),
    )


@callback
@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "update_manager/updates"})
def _handle_updates(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    data = _get_data(hass)
    if not data:
        connection.send_result(msg["id"], {"updates": []})
        return

    install_manager = data.install_manager
    updates = []
    for entry in data.coordinator.cache.values():
        pending = install_manager.pending_for(entry["entity_id"])
        updates.append(
            {
                **entry,
                "pending_install": (
                    {
                        "to_version": pending.to_version,
                        "execute_at": pending.execute_at.isoformat(),
                        # Added 2026-08-01, direct user feedback: History
                        # shows "Announced" as its own fact once installed,
                        # but a still-pending "ready" update (this exact
                        # PendingAnnouncement, already real, not projected)
                        # had no equivalent anywhere in the live dialog.
                        "announced_at": pending.announced_at.isoformat(),
                    }
                    if pending is not None
                    else None
                ),
            }
        )
    connection.send_result(
        msg["id"],
        {
            "updates": updates,
            # Only ever non-empty once a *second* device from the same
            # Zigbee network/model/version is asked to install while one is
            # already in flight, see rollout_manager.py's own docstring.
            # The panel renders these as their own queue card(s), above the
            # normal ready/waiting/blocked groups.
            "rollout_groups": data.rollout_manager.rollout_groups_snapshot(),
        },
    )


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command({vol.Required("type"): "update_manager/refresh_community_verdicts"})
async def _handle_refresh_community_verdicts(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """The panel's own manual refresh button, direct user feedback,
    2026-07-25: pressing it should also pull in the latest community-votes
    data, not just whatever CommunityVerdictManager's own hour-long cache
    still happens to have. Awaited here (not fired as a background task)
    so the panel's own immediately-following update_manager/updates call
    sees the freshly-patched cache, not a stale one with a refresh still
    in flight."""
    data = _get_data(hass)
    if not data:
        connection.send_error(msg["id"], "not_found", "Update Manager isn't set up")
        return
    await data.coordinator.async_force_refresh_community_verdicts()
    await _async_reconcile_my_votes(hass, data)
    connection.send_result(msg["id"])


async def _async_reconcile_my_votes(hass: HomeAssistant, data: UpdateManagerData) -> None:
    """Force-checks every locally remembered vote against live community-votes
    data right now, regardless of _STALE_VOTE_GRACE_PERIOD -- the panel's own
    manual refresh button is an explicit, deliberate "tell me the truth now"
    action (direct user feedback, 2026-08-01: "ik zou dit alsnog in de
    refresh knop willen"), unlike the passive per-dialog check in
    _handle_verdict_for_version, which respects that grace period so a vote
    just cast isn't second-guessed while community-votes' own Action might
    still be processing it. A per-jump_key fetch failure is skipped, not
    treated as "confirmed gone" -- same reasoning as fetch_ok elsewhere in
    this file (a transient network hiccup must never forget a real vote).

    All jump_keys are fetched concurrently (found by review, 2026-08-01:
    the previous one-at-a-time loop turned N remembered votes into N
    sequential round-trips, each waiting for the last) -- independent
    fetches with no shared state until the forgetting step below, so
    there's nothing to serialize for."""
    username = data.github_auth_manager.linked_username
    if not username:
        return

    async def _fetch(jump_key: str) -> tuple[str, str | None] | None:
        to_version_path, _, from_version = jump_key.partition("::")
        try:
            return jump_key, await async_fetch_vote_for_jump_key(hass, to_version_path, from_version, username)
        except Exception:
            return None

    results = await asyncio.gather(*(_fetch(jump_key) for jump_key in data.my_votes_manager.jump_keys()))
    # async_forget_many, not async_forget in a loop -- found by review,
    # 2026-08-01: a per-key await here meant N genuinely-gone votes did N
    # sequential full Store.async_save() writes for no reason (nothing
    # reads self._votes in between them), even after the fetches above were
    # already made concurrent.
    stale_jump_keys = [jump_key for jump_key, live_vote in (r for r in results if r is not None) if live_vote is None]
    await data.my_votes_manager.async_forget_many(stale_jump_keys)


async def _async_fetch_github_release_notes(
    hass: HomeAssistant,
    release_url: str | None,
    access_token: str | None,
    from_version: str | None = None,
    to_version: str | None = None,
) -> tuple[str, str, str | None, str | None] | None:
    """(owner, repo, notes, corrected_url) straight from GitHub's own
    release(s) at this exact release_url -- a last-resort fallback for the
    panel's changelog/release-notes section when neither the entity's own
    UpdateEntityFeature.RELEASE_NOTES fetch nor its release_summary
    attribute had anything to show. Not a rare edge case: HACS's own
    async_release_notes() (custom_components/hacs/update.py) returns None
    whenever pending_restart is still true, or the installed version isn't
    in its own published_tags; Home Assistant Supervisor's own update entity
    doesn't support UpdateEntityFeature.RELEASE_NOTES at all (verified
    against hassio's own update.py, 2026-08-01) -- confirmed live, direct
    user feedback: "dus het is absoluut niet alleen hacs". owner/repo are
    returned alongside the notes so the frontend can turn #1234/@username
    references in the notes into real GitHub links without having to
    re-parse release_url itself.

    to_version, when given, corrects release_url's own tag before doing
    anything else, by matching it against the fetched releases list (see
    github_release_notes.find_release_by_version's own docstring) -- direct
    user feedback, 2026-08-01, found on a real downgrade (2.0 -> 1.0):
    release_url reflects "latest available", not "what was actually
    installed" (true for HACS specifically, confirmed against its own
    source), so trusting its own embedded tag blindly showed 2.0's notes for
    an entry that actually downgraded to 1.0. Left uncorrected (silently, no
    error) whenever the match isn't found in the fetched page -- same
    graceful "best effort, never loud about it" treatment as everything else
    in this fallback. A successful to_version match's own body is returned
    directly (once no from_version compile also succeeded) rather than
    re-requesting the exact same release a second time from the single-tag
    endpoint below -- that fetch already has it.

    corrected_url is that same match's own `html_url` (GitHub's own field
    for the release's real web page), None whenever no correction happened
    (to_version missing, or no match found in the fetched page) -- found by
    review, 2026-08-03: the notes body was corrected for a downgrade, but
    the "Read release announcement" link the frontend builds from the
    original, uncorrected release_url was never updated to match, so it
    kept pointing at the newest release even once the notes right above it
    correctly described an older one. The frontend substitutes this in
    place of its own release_url whenever it's non-None, see
    insertReleaseNotesSection's own comment.

    When from_version is given, tries to compile notes across every release
    skipped between from_version and the (possibly to_version-corrected)
    target tag first (same gap HACS's own async_release_notes() already
    closes when it can, see github_release_notes.compile_release_range's own
    docstring) -- falls back to the single release's own body (the
    from_version-less behavior) whenever that listing fetch fails or turns
    up nothing usable, so a transient rate-limit/network hiccup on the
    (heavier) list endpoint never loses the notes the single-release
    endpoint would have found on its own.

    Uses the linked GitHub account's own token when available (5000
    requests/hour) rather than requiring it -- an unauthenticated request
    still works for a public repo (60/hour), this is a nice-to-have
    enrichment, not something worth gating behind linking an account (unlike
    voting, which genuinely needs an identity). None whenever release_url
    doesn't parse as a real GitHub release URL, or the lookup fails/404s for
    any reason -- same graceful "nothing to add" treatment used throughout
    this module."""
    parsed = parse_release_url(release_url)
    if parsed is None:
        return None
    owner, repo, tag = parsed
    headers = {"Accept": "application/vnd.github+json"}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    session = async_get_clientsession(hass)

    if from_version or to_version:
        try:
            async with session.get(
                f"https://api.github.com/repos/{owner}/{repo}/releases", headers=headers, timeout=10
            ) as response:
                if response.status == 200:
                    releases = await response.json()
                    matched = find_release_by_version(releases, to_version) if to_version else None
                    corrected_url = matched.get("html_url") if matched is not None else None
                    if matched is not None:
                        tag = matched.get("tag_name", tag)
                    if from_version:
                        compiled = compile_release_range(releases, from_version, tag)
                        if compiled:
                            return (owner, repo, compiled, corrected_url)
                    # matched already carries this exact release's own body --
                    # found by review, 2026-08-01: falling through to the
                    # single-tag fetch below used to re-request the very same
                    # release a second time whenever from_version was absent,
                    # or its own compile attempt above found nothing usable.
                    if matched is not None:
                        return (owner, repo, matched.get("body") or None, corrected_url)
        except Exception:
            pass

    try:
        async with session.get(
            f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}", headers=headers, timeout=10
        ) as response:
            if response.status != 200:
                return (owner, repo, None, None)
            data = await response.json()
    except Exception:
        return (owner, repo, None, None)
    return (owner, repo, data.get("body") or None, None)


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required("type"): "update_manager/github_release_notes",
        vol.Required("release_url"): str,
        vol.Optional("from_version"): str,
        vol.Optional("to_version"): str,
    }
)
async def _handle_github_release_notes(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    data = _get_data(hass)
    if not data:
        connection.send_error(msg["id"], "not_found", "Update Manager isn't set up")
        return
    access_token = await data.github_auth_manager.async_get_valid_access_token()
    result = await _async_fetch_github_release_notes(
        hass, msg["release_url"], access_token, msg.get("from_version"), msg.get("to_version")
    )
    if result is None:
        connection.send_result(msg["id"], {"notes": None, "owner": None, "repo": None, "corrected_url": None})
        return
    owner, repo, notes, corrected_url = result
    connection.send_result(msg["id"], {"notes": notes, "owner": owner, "repo": repo, "corrected_url": corrected_url})


@callback
@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "update_manager/install_log"})
def _handle_install_log(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    data = _get_data(hass)
    entries = data.install_log.entries if data else []
    connection.send_result(msg["id"], {"entries": entries})


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required("type"): "update_manager/cancel_pending_install",
        vol.Required("entity_id"): str,
        # The version to cancel auto-install for -- required, not read off
        # an existing PendingAnnouncement server-side, since this can now
        # be called before one exists yet (still "waiting", only
        # projected, see install_manager.py's own async_cancel).
        vol.Required("to_version"): str,
    }
)
async def _handle_cancel_pending_install(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    data = _get_data(hass)
    if not data:
        connection.send_error(msg["id"], "not_found", "Update Manager isn't set up")
        return
    await data.install_manager.async_cancel(msg["entity_id"], msg["to_version"])
    connection.send_result(msg["id"])


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required("type"): "update_manager/install",
        vol.Required("entity_id"): str,
        vol.Optional("backup"): bool,
    }
)
async def _handle_install(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """Explicit, user-initiated install (the panel's own Install button) --
    not a plain passthrough to update.install, because the entity might
    currently be "waiting" (postponed) or skipped (either a genuine user
    skip, or our own hide_postponed auto-skip). Direct user feedback
    (2026-07-17): choosing to install right now is a deliberate override of
    all of that -- postponed/skipped should clear immediately, not linger
    until the install itself finishes and a fresh state_changed happens to
    reclassify it (which, for a plain in_progress toggle, coordinator.py's
    own dedup wouldn't even trigger a re-classification for at all).

    update.install itself is dispatched as its own task, not awaited here
    (blocking=True would tie up this handler for as long as the actual
    install takes, e.g. a slow firmware flash) -- its own in_progress/
    installed_version attributes stream back to the panel live through the
    normal hass state-push mechanism regardless (see the panel's own
    _updateInstallProgress/_updateDialogProgress)."""
    entity_id = msg["entity_id"]
    data = _get_data(hass)
    if data:
        await data.staging_skip_manager.async_forget(entity_id)
    state = hass.states.get(entity_id)
    if state is not None and state.attributes.get("skipped_version"):
        await hass.services.async_call("update", "clear_skipped", {"entity_id": entity_id}, blocking=True)
    service_data: dict[str, Any] = {"entity_id": entity_id}
    if msg.get("backup"):
        service_data["backup"] = True

    # A no-op for anything that isn't part of an active multi-device Zigbee
    # rollout (see rollout_manager.py's own docstring): queued means a
    # sibling device from the same network/model/version is already
    # installing right now; RolloutManager calls update.install for this
    # one itself once it's this entity's turn, so this handler must not
    # also dispatch it here. is_auto=False: a real, user-initiated click,
    # never attributed as "auto_installed" in install_log.py even if it
    # ends up dispatched later by RolloutManager instead of immediately.
    to_version = state.attributes.get("latest_version") if state else None
    queued = False
    if data and to_version:
        result = await data.rollout_manager.async_request_install(
            entity_id, to_version, service_data, is_auto=False
        )
        queued = result == "queued"
    if not queued:
        hass.async_create_task(hass.services.async_call("update", "install", service_data, blocking=True))
    if data:
        # Awaited, not left to the state_changed event clear_skipped above
        # already schedules on its own -- that's a background task HA
        # fires and forgets, not guaranteed to have run yet by the time
        # this handler returns and the panel's own post-call _loadAll()
        # re-fetches (same race already fixed once this session for
        # save_settings/staging_skip.py's own skip/unskip calls).
        await data.coordinator.async_refresh_one(entity_id)
    connection.send_result(msg["id"], {"queued": queued})


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {vol.Required("type"): "update_manager/skip", vol.Required("entity_id"): str}
)
async def _handle_skip(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """A genuine user-initiated skip (the panel's own Skip button) -- not
    a plain passthrough like _handle_unskip below, because this one can
    target an entity staging_skip.py already auto-skipped for
    hide_postponed. Found live: clicking Skip there "leek helemaal niks te
    doen" -- skipped_version already equalled latest_version in real HA
    state (the service call was a genuine no-op, no state_changed fired),
    and is_own_skip kept claiming the entity as staging_skip.py's own,
    leaving it classified as "waiting"/postponed instead of turning into a
    real, visible "Skipped". Forgetting the record *before* calling the
    service (so is_own_skip already disagrees by the time anything
    re-evaluates), then forcing coordinator.py to refresh this one entity
    immediately (since a no-op service call fires no event to trigger that
    on its own) fixes both halves of that."""
    entity_id = msg["entity_id"]
    data = _get_data(hass)
    if data:
        await data.staging_skip_manager.async_forget(entity_id)
    await hass.services.async_call("update", "skip", {"entity_id": entity_id}, blocking=True)
    if data:
        await data.coordinator.async_refresh_one(entity_id)
    connection.send_result(msg["id"])


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {vol.Required("type"): "update_manager/unskip", vol.Required("entity_id"): str}
)
async def _handle_unskip(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    # No bookkeeping of our own needed for the skip itself -- this only
    # ever applies to a genuine user-initiated skip (see coordinator.py's
    # own is_own_skip distinction, and the panel's "Skipped" group), never
    # one staging_skip.py itself set, so there's no internal record to
    # reconcile on our side. The explicit refresh below is needed anyway:
    # found live, the panel's own post-call _loadAll() saw stale data
    # (still "Skipped") requiring a manual page refresh -- clear_skipped's
    # own resulting state_changed event is handled by coordinator.py as a
    # separate scheduled task, not guaranteed to have run yet by the time
    # this handler returns (same race already fixed for _handle_skip/
    # _handle_install).
    entity_id = msg["entity_id"]
    await hass.services.async_call("update", "clear_skipped", {"entity_id": entity_id}, blocking=True)
    data = _get_data(hass)
    if data:
        await data.coordinator.async_refresh_one(entity_id)
    connection.send_result(msg["id"])


@callback
@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "update_manager/get_settings"})
def _handle_get_settings(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    entry = _get_entry(hass)
    options = dict(entry.options) if entry else {}
    connection.send_result(
        msg["id"],
        {
            "options": options,
            "defaults": DEFAULT_WAIT_DAYS,
            "hard_excluded_entities": hard_excluded_entity_ids(hass),
        },
    )


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    # extra=vol.REMOVE_EXTRA (not the plain-dict default of rejecting
    # unknown keys): found via live testing that a config entry's stored
    # options can carry fields left over from an earlier settings design
    # (e.g. the removed *_blocked/*_mode from before 2026-07-16) that HA
    # never automatically cleans up. The panel now filters those out on its
    # own (see pickKnownSettings in the panel JS), but the backend
    # shouldn't hard-fail the whole save over stale keys either -- quietly
    # dropping them here is the more robust half of that same fix.
    vol.All(
        vol.Schema(
            {
                vol.Required("type"): "update_manager/save_settings",
                vol.Required(CONF_ENABLED): bool,
                vol.Required(CONF_SMALL_WAIT_DAYS): vol.All(vol.Coerce(int), vol.Range(min=0, max=365)),
                vol.Required(CONF_SMALL_AUTO_INSTALL): bool,
                vol.Required(CONF_MEDIUM_WAIT_DAYS): vol.All(vol.Coerce(int), vol.Range(min=0, max=365)),
                vol.Required(CONF_MEDIUM_AUTO_INSTALL): bool,
                vol.Required(CONF_LARGE_WAIT_DAYS): vol.All(vol.Coerce(int), vol.Range(min=0, max=365)),
                vol.Required(CONF_LARGE_AUTO_INSTALL): bool,
                vol.Required(CONF_ANNOUNCE_HOURS): vol.All(vol.Coerce(int), vol.Range(min=1, max=336)),
                vol.Required(CONF_EXCLUDED_ENTITIES): [str],
                vol.Required(CONF_HIDE_POSTPONED): bool,
                vol.Required(CONF_TRUSTED_VOTERS): [str],
            },
            extra=vol.REMOVE_EXTRA,
        )
    )
)
async def _handle_save_settings(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    entry = _get_entry(hass)
    if not entry:
        connection.send_error(msg["id"], "not_found", "Update Manager isn't set up")
        return
    options = {k: v for k, v in msg.items() if k not in ("type", "id")}
    hass.config_entries.async_update_entry(entry, options=options)
    # Applied directly here too, awaited -- not just left to HA's own
    # config entry update-listener (__init__.py's update_listener), which
    # still also fires on its own (harmless: re-applying the same
    # already-applied state is a no-op), but only as a background task HA
    # schedules, never awaited by this handler. Found live: the panel's
    # own save button reloads Updates/History right after this call
    # resolves, and saw stale, not-yet-recomputed data (a newly-enabled
    # "hide postponed" hadn't actually skipped anything yet) because that
    # background task hadn't run yet at that point.
    await async_apply_options(hass, options)
    connection.send_result(msg["id"])


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command({vol.Required("type"): "update_manager/github_link_start"})
async def _handle_github_link_start(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    data = _get_data(hass)
    if not data:
        connection.send_error(msg["id"], "not_found", "Update Manager isn't set up")
        return
    result = await data.github_auth_manager.async_start_device_flow()
    connection.send_result(msg["id"], result)


@callback
@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "update_manager/github_link_status"})
def _handle_github_link_status(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    data = _get_data(hass)
    status = data.github_auth_manager.link_status() if data else {"status": "idle", "username": None}
    connection.send_result(msg["id"], status)


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command({vol.Required("type"): "update_manager/github_unlink"})
async def _handle_github_unlink(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    data = _get_data(hass)
    if not data:
        connection.send_error(msg["id"], "not_found", "Update Manager isn't set up")
        return
    await data.github_auth_manager.async_unlink()
    connection.send_result(msg["id"])


def _release_url_for_version(hass: HomeAssistant, data: UpdateManagerData, entity_id: str, version: str) -> str | None:
    """The release_url that applies to this exact (entity_id, version) pair,
    the single place that decides this instead of trusting each caller to
    reconstruct it correctly (found by review, 2026-07-22: a first version
    of this had the frontend supply release_url itself, fragile, easy for a
    future caller to get subtly wrong or stale). Checked in two places:
    install_log.py's own entries (a specific past install, e.g. voting from
    the History tab, its own release_url captured at that exact time) first,
    since that's authoritative for a version that isn't the entity's current
    one; the entity's live state second, for the still-pending, not-yet-
    installed case, where no install_log entry exists yet."""
    for entry in reversed(data.install_log.entries):
        if entry["entity_id"] == entity_id and entry["to_version"] == version:
            return entry.get("release_url")
    state = hass.states.get(entity_id)
    if state is not None and state.attributes.get("latest_version") == version:
        return state.attributes.get("release_url")
    return None


def _from_version_for_version(hass: HomeAssistant, data: UpdateManagerData, entity_id: str, version: str) -> str | None:
    """The from_version (the version upgraded *from*) that applies to this
    exact (entity_id, version) pair -- mirrors _release_url_for_version's
    own two-case shape exactly, so a vote/verdict lookup resolves the whole
    jump (not just the destination) server-side, the same defensive
    precedent this file already established for release_url. Checked in the
    same two places: install_log.py's own entries (a specific past install,
    e.g. voting from the History tab, already carries its own from_version)
    first; the entity's live installed_version state second, for the
    still-pending, not-yet-installed case."""
    for entry in reversed(data.install_log.entries):
        if entry["entity_id"] == entity_id and entry["to_version"] == version:
            return entry.get("from_version")
    state = hass.states.get(entity_id)
    if state is not None and state.attributes.get("latest_version") == version:
        return state.attributes.get("installed_version")
    return None


def _resolve_identity_for_version(
    hass: HomeAssistant, data: UpdateManagerData, entity_id: str, version: str
) -> ResolvedIdentity | None:
    """_release_url_for_version + _from_version_for_version +
    resolve_full_identity, the one pairing both _handle_verdict_for_version
    and _handle_vote need, resolved once instead of each handler repeating
    these steps on its own (found by review: resolve_full_identity does a
    device_registry lookup, worth not duplicating). None (rather than
    calling resolve_full_identity with a bogus from_version) whenever the
    from_version can't be determined at all -- same "can't identify this"
    treatment as a missing release_url."""
    release_url = _release_url_for_version(hass, data, entity_id, version)
    from_version = _from_version_for_version(hass, data, entity_id, version)
    if from_version is None:
        return None
    return resolve_full_identity(hass, entity_id, release_url, version, from_version)


async def _async_resolve_my_verdict(hass: HomeAssistant, data: UpdateManagerData, identity: ResolvedIdentity) -> str | None:
    """Your own past verdict on this exact identity, local-cache-first
    (my_votes.py, immediately available even just after voting, before
    community-votes' own Action has processed it), falling back to your
    real vote file on community-votes (one request, only when the local
    record has nothing -- e.g. a vote cast before my_votes.py existed) and
    backfilling the local record on success. The one place both
    _handle_verdict_for_version ("what did I vote") and _handle_vote
    ("is this a change of vote") need this exact lookup (found by review:
    both used to repeat the same local-then-fallback-then-backfill steps
    by hand, and the _handle_vote copy was missing the backfill, silently
    paying the extra request again on every future check until an actual
    vote was cast)."""
    my_verdict = data.my_votes_manager.my_verdict(identity.jump_key)
    if my_verdict is not None:
        return my_verdict
    username = data.github_auth_manager.linked_username
    if not username:
        return None
    my_verdict = await async_fetch_my_vote(hass, identity, username)
    if my_verdict is not None:
        await data.my_votes_manager.async_remember(identity.jump_key, my_verdict)
    return my_verdict


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required("type"): "update_manager/verdict_for_version",
        vol.Required("entity_id"): str,
        vol.Required("version"): str,
    }
)
async def _handle_verdict_for_version(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    data = _get_data(hass)
    if not data:
        connection.send_error(msg["id"], "not_found", "Update Manager isn't set up")
        return
    # Reported separately from "verdict", not left for the frontend to infer
    # from a null verdict alone: found by review, 2026-07-22, many update
    # entities (every Zigbee/ZHA device firmware update, for one, the exact
    # category this project's own rollout-pacing feature paces) have no
    # release_url at all and can never be identified, "not yet rated" and
    # "can never be rated" look identical as a bare null verdict otherwise.
    # The panel uses this to hide vote controls entirely for these, instead
    # of offering a button that would always fail.
    identity = _resolve_identity_for_version(hass, data, msg["entity_id"], msg["version"])
    # Deliberately always the uncached fetch, never CommunityVerdictManager's
    # own time-cached entry (tried once, reverted live 2026-07-22): that
    # cache is fine for the passive Updates-tab badge, up to an hour stale
    # is invisible there, but a user opening this exact dialog to check on a
    # vote they just cast found it showing that same up-to-an-hour-old
    # cached answer even after clicking the panel's own refresh button,
    # since nothing about a manual dialog open invalidates that cache
    # early. One extra live HTTP GET per dialog open is the right,
    # deliberate price for "always tell the truth right now" on an
    # interactive, user-initiated check.
    # Gathered concurrently, not two sequential awaits -- found by code
    # review, 2026-07-27: these are fully independent (the community-verdict
    # fetch never depends on your own vote, or vice versa), but
    # _async_resolve_my_verdict's own fallback path (no local my_votes.py
    # record yet) does its own separate live HTTP GET too, so the old
    # sequential order doubled this dialog-open's real network latency in
    # exactly that case.
    # Resolved up front, not after the fetch: passed straight into
    # async_fetch_verdict_uncached so it can exclude your own entry from
    # the generic list *before* capping it, and find your own reason via a
    # direct, cap-independent lookup instead of searching the (possibly
    # already-missing-you) capped result afterward -- found by review,
    # 2026-07-29: the previous post-hoc "search the capped list for my own
    # username" approach could silently come back empty whenever enough
    # other, more recent votes existed, even though a real reason existed
    # (see problematic_reasons_from_payload's own docstring for the full
    # reasoning).
    username = data.github_auth_manager.linked_username if data else None
    if identity is not None:
        (
            (verdict, other_jumps, trusted_vote, trusted_voters_matched, problematic_reasons, my_reason, my_live_verdict, fetch_ok),
            my_verdict,
        ) = await asyncio.gather(
            async_fetch_verdict_uncached(hass, identity, data.community_verdict_manager.trusted_voters, username),
            _async_resolve_my_verdict(hass, data, identity),
        )
        # Self-heals my_votes.py's own local record against a vote that's
        # been deleted directly on community-votes (direct user feedback,
        # 2026-08-01: the panel kept showing "you voted" with no way to
        # vote again, since the local record alone was ever consulted once
        # it had *any* entry -- see _async_resolve_my_verdict's own
        # docstring). Both this fetch and _async_resolve_my_verdict's own
        # cache-first lookup already ran above; reusing my_live_verdict here
        # costs nothing extra. Gated on all three: fetch_ok (never trust an
        # absence caused by a transient failure, not a real one -- see
        # EMPTY_VERDICT_RESULT's own comment), my_verdict is not None (only
        # a remembered vote can ever need forgetting), and is_stale (a vote
        # just cast is expected to be briefly missing from the live payload
        # while community-votes' own Action is still processing it -- must
        # keep being trusted regardless of what this same fetch just said,
        # or that exact "not yet rated" bug comes right back).
        if fetch_ok and my_verdict is not None and my_live_verdict is None:
            if data.my_votes_manager.is_stale(identity.jump_key, _STALE_VOTE_GRACE_PERIOD):
                await data.my_votes_manager.async_forget(identity.jump_key)
                my_verdict = None
    else:
        verdict, other_jumps, trusted_vote, trusted_voters_matched, problematic_reasons, my_reason, _, _ = EMPTY_VERDICT_RESULT
        my_verdict = None
    connection.send_result(
        msg["id"],
        {
            "verdict": verdict,
            "identifiable": identity is not None,
            "my_verdict": my_verdict,
            # Every other jump landing on this same destination version
            # (direct user feedback, 2026-07-24), my own jump excluded --
            # "verdict"/"my_verdict" above already are my own jump, always
            # shown first/primary in the dialog by construction.
            "other_jumps": other_jumps,
            # Whether a configured trusted voter is among the people who
            # voted on this exact jump (direct user feedback, 2026-07-27) --
            # the same fact community_verdict.py's own cache already
            # computes for the entity's *current* pending jump, now also
            # available for an arbitrary History entry's jump.
            "trusted_vote": trusted_vote,
            "trusted_voters_matched": trusted_voters_matched,
            # Every *other* problematic voter's own reason_category/notes/
            # link for my own jump (direct user feedback, 2026-07-29): a
            # vote's reason used to be write-only, collected on submission
            # but never read back anywhere. Excludes your own (see
            # my_reason below).
            "problematic_reasons": problematic_reasons,
            # Your own reason, split out above -- shown attached to your own
            # "You reported this jump as problematic" row instead of buried,
            # unattributed, in the general list.
            "my_reason": my_reason,
        },
    )


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required("type"): "update_manager/vote",
        vol.Required("entity_id"): str,
        # The exact version being voted on, either a specific install_log
        # entry (the History tab) or the entity's own current pending
        # version, see _release_url_for_version's own docstring for how the
        # matching release_url is resolved from just this.
        vol.Required("version"): str,
        vol.Required("verdict"): vol.In(["healthy", "problematic"]),
        vol.Optional("reason_category"): vol.In(REASON_CATEGORIES),
        vol.Optional("notes"): str,
        vol.Optional("link"): str,
    }
)
async def _handle_vote(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    data = _get_data(hass)
    if not data:
        connection.send_error(msg["id"], "not_found", "Update Manager isn't set up")
        return

    identity = _resolve_identity_for_version(hass, data, msg["entity_id"], msg["version"])
    if identity is None:
        connection.send_error(msg["id"], "not_identifiable", "This update can't be identified for voting yet")
        return

    access_token = await data.github_auth_manager.async_get_valid_access_token()
    if access_token is None:
        connection.send_error(msg["id"], "not_linked", "Link your GitHub account first")
        return

    # Checked before submitting, not derived from the vote itself: this is
    # the one place that already knows whether you voted on this exact
    # version before, so the panel can say "updated" instead of "submitted"
    # -- community-votes' own process-vote.yml now replaces a repeat vote
    # from the same person instead of rejecting it as a duplicate
    # (2026-07-23, direct user feedback: changing your mind about an update
    # you already rated is a completely normal thing to want). Same
    # local-then-fallback lookup _handle_verdict_for_version uses, so this
    # reads correctly even for a vote cast before my_votes.py existed.
    is_vote_update = await _async_resolve_my_verdict(hass, data, identity) is not None

    try:
        await async_submit_vote(
            hass,
            access_token,
            identity,
            msg["verdict"],
            msg.get("reason_category"),
            msg.get("notes"),
            msg.get("link"),
        )
    except Exception:
        connection.send_error(msg["id"], "vote_failed", "Couldn't submit the vote, try again")
        return
    await data.my_votes_manager.async_remember(identity.jump_key, msg["verdict"])
    # Mirrors process-vote.yml's own "Asymmetric weight for the repo owner
    # (hacs only)" rule (weight 0 for a maintainer's own "healthy" vote --
    # not an independent verification, just the maker approving their own
    # release) so the panel can say so instead of silently showing a
    # standing that doesn't reflect the vote just cast. Found live,
    # 2026-07-30: a repo owner voting healthy on their own release saw
    # "0 healthy" right after "Thanks for your vote!" with no explanation.
    linked_username = data.github_auth_manager.linked_username
    is_own_repo_healthy_vote = bool(
        msg["verdict"] == "healthy"
        and identity.owner_repo
        and linked_username
        and identity.owner_repo.split("/", 1)[0].lower() == linked_username.lower()
    )
    connection.send_result(
        msg["id"], {"updated": is_vote_update, "own_repo_healthy_vote": is_own_repo_healthy_vote}
    )


def async_setup_websocket_api(hass: HomeAssistant) -> None:
    """Registers the commands once. Safe to call again on entry reload
    (e.g. after saving settings) -- HA raises on a duplicate registration,
    so this is guarded rather than relying on callers."""
    if hass.data.get(_WS_REGISTERED):
        return
    hass.data[_WS_REGISTERED] = True
    websocket_api.async_register_command(hass, _handle_updates)
    websocket_api.async_register_command(hass, _handle_refresh_community_verdicts)
    websocket_api.async_register_command(hass, _handle_github_release_notes)
    websocket_api.async_register_command(hass, _handle_install_log)
    websocket_api.async_register_command(hass, _handle_cancel_pending_install)
    websocket_api.async_register_command(hass, _handle_install)
    websocket_api.async_register_command(hass, _handle_skip)
    websocket_api.async_register_command(hass, _handle_unskip)
    websocket_api.async_register_command(hass, _handle_get_settings)
    websocket_api.async_register_command(hass, _handle_save_settings)
    websocket_api.async_register_command(hass, _handle_github_link_start)
    websocket_api.async_register_command(hass, _handle_github_link_status)
    websocket_api.async_register_command(hass, _handle_github_unlink)
    websocket_api.async_register_command(hass, _handle_vote)
    websocket_api.async_register_command(hass, _handle_verdict_for_version)
