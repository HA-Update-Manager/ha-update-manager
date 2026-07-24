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
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import (
    CONF_ANNOUNCE_HOURS,
    CONF_BIG_AUTO_INSTALL,
    CONF_BIG_WAIT_DAYS,
    CONF_ENABLED,
    CONF_EXCLUDED_ENTITIES,
    CONF_HIDE_POSTPONED,
    CONF_MEDIUM_AUTO_INSTALL,
    CONF_MEDIUM_WAIT_DAYS,
    CONF_SMALL_AUTO_INSTALL,
    CONF_SMALL_WAIT_DAYS,
    CONF_TRUSTED_VOTERS,
    DOMAIN,
    PROFILE_PRESETS,
)
from .community_verdict import async_fetch_my_vote, async_fetch_verdict_uncached
from .community_vote import async_submit_vote
from .coordinator import (
    excluded_entities_from_options,
    hard_excluded_entity_ids,
    rules_from_options,
    trusted_voters_from_options,
)
from .device_identity import resolve_full_identity
from .hacs_identity import ResolvedIdentity
from .install_manager import auto_install_rules_from_options
from .vote_issue_body import REASON_CATEGORIES

_WS_REGISTERED = f"{DOMAIN}_ws_registered"


async def async_apply_options(hass: HomeAssistant, options: dict) -> None:
    """Applies newly-saved settings to every manager in place, no reload
    needed -- shared by _handle_save_settings below (awaited directly, so
    the panel's own post-save reload sees fresh data) and __init__.py's
    update_listener (HA's own config-entry update mechanism, fired as an
    unawaited background task shortly after -- a harmless, idempotent
    re-application of the same already-applied state). Found by review:
    the two used to duplicate this exact sequence by hand, needing every
    future setting/manager added here to be edited in both places."""
    data = hass.data.get(DOMAIN)
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
    await data["coordinator"].async_update_rules(
        rules_from_options(options), excluded_entities_from_options(options)
    )
    data["install_manager"].update_rules(auto_install_rules_from_options(options))
    data["community_verdict_manager"].set_trusted_voters(trusted_voters_from_options(options))

    async def _apply_staging_skip() -> None:
        await data["staging_skip_manager"].async_update_enabled(options.get(CONF_HIDE_POSTPONED, True))
        await data["staging_skip_manager"].async_set_master_enabled(master_enabled)

    await asyncio.gather(
        data["install_manager"].async_set_master_enabled(master_enabled),
        _apply_staging_skip(),
    )


@callback
@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "update_manager/updates"})
def _handle_updates(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    data = hass.data.get(DOMAIN)
    if not data:
        connection.send_result(msg["id"], {"updates": []})
        return

    install_manager = data["install_manager"]
    updates = []
    for entry in data["coordinator"].cache.values():
        pending = install_manager.pending_for(entry["entity_id"])
        updates.append(
            {
                **entry,
                "pending_install": (
                    {"to_version": pending.to_version, "execute_at": pending.execute_at.isoformat()}
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
            "rollout_groups": data["rollout_manager"].rollout_groups_snapshot(),
        },
    )


@callback
@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "update_manager/install_log"})
def _handle_install_log(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    data = hass.data.get(DOMAIN)
    entries = data["install_log"].entries if data else []
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
    data = hass.data.get(DOMAIN)
    if not data:
        connection.send_error(msg["id"], "not_found", "Update Manager isn't set up")
        return
    await data["install_manager"].async_cancel(msg["entity_id"], msg["to_version"])
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
    data = hass.data.get(DOMAIN)
    if data:
        await data["staging_skip_manager"].async_forget(entity_id)
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
        result = await data["rollout_manager"].async_request_install(
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
        await data["coordinator"].async_refresh_one(entity_id)
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
    data = hass.data.get(DOMAIN)
    if data:
        await data["staging_skip_manager"].async_forget(entity_id)
    await hass.services.async_call("update", "skip", {"entity_id": entity_id}, blocking=True)
    if data:
        await data["coordinator"].async_refresh_one(entity_id)
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
    data = hass.data.get(DOMAIN)
    if data:
        await data["coordinator"].async_refresh_one(entity_id)
    connection.send_result(msg["id"])


@callback
@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "update_manager/get_settings"})
def _handle_get_settings(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    entries = hass.config_entries.async_entries(DOMAIN)
    options = dict(entries[0].options) if entries else {}
    connection.send_result(
        msg["id"],
        {
            "options": options,
            "profiles": PROFILE_PRESETS,
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
                vol.Required(CONF_BIG_WAIT_DAYS): vol.All(vol.Coerce(int), vol.Range(min=0, max=365)),
                vol.Required(CONF_BIG_AUTO_INSTALL): bool,
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
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_error(msg["id"], "not_found", "Update Manager isn't set up")
        return
    options = {k: v for k, v in msg.items() if k not in ("type", "id")}
    hass.config_entries.async_update_entry(entries[0], options=options)
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
    data = hass.data.get(DOMAIN)
    if not data:
        connection.send_error(msg["id"], "not_found", "Update Manager isn't set up")
        return
    result = await data["github_auth_manager"].async_start_device_flow()
    connection.send_result(msg["id"], result)


@callback
@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "update_manager/github_link_status"})
def _handle_github_link_status(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    data = hass.data.get(DOMAIN)
    status = data["github_auth_manager"].link_status() if data else {"status": "idle", "username": None}
    connection.send_result(msg["id"], status)


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command({vol.Required("type"): "update_manager/github_unlink"})
async def _handle_github_unlink(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    data = hass.data.get(DOMAIN)
    if not data:
        connection.send_error(msg["id"], "not_found", "Update Manager isn't set up")
        return
    await data["github_auth_manager"].async_unlink()
    connection.send_result(msg["id"])


def _release_url_for_version(hass: HomeAssistant, data: dict, entity_id: str, version: str) -> str | None:
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
    for entry in reversed(data["install_log"].entries):
        if entry["entity_id"] == entity_id and entry["to_version"] == version:
            return entry.get("release_url")
    state = hass.states.get(entity_id)
    if state is not None and state.attributes.get("latest_version") == version:
        return state.attributes.get("release_url")
    return None


def _resolve_identity_for_version(
    hass: HomeAssistant, data: dict, entity_id: str, version: str
) -> ResolvedIdentity | None:
    """_release_url_for_version + resolve_full_identity, the one pairing
    both _handle_verdict_for_version and _handle_vote need, resolved once
    instead of each handler repeating both steps on its own (found by
    review: resolve_full_identity does a device_registry lookup, worth not
    duplicating)."""
    release_url = _release_url_for_version(hass, data, entity_id, version)
    return resolve_full_identity(hass, entity_id, release_url, version)


async def _async_resolve_my_verdict(hass: HomeAssistant, data: dict, identity: ResolvedIdentity) -> str | None:
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
    my_verdict = data["my_votes_manager"].my_verdict(identity.votes_path)
    if my_verdict is not None:
        return my_verdict
    username = data["github_auth_manager"].linked_username
    if not username:
        return None
    my_verdict = await async_fetch_my_vote(hass, identity, username)
    if my_verdict is not None:
        await data["my_votes_manager"].async_remember(identity.votes_path, my_verdict)
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
    data = hass.data.get(DOMAIN)
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
    verdict = await async_fetch_verdict_uncached(hass, identity) if identity is not None else None
    my_verdict = await _async_resolve_my_verdict(hass, data, identity) if identity is not None else None
    connection.send_result(
        msg["id"], {"verdict": verdict, "identifiable": identity is not None, "my_verdict": my_verdict}
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
    data = hass.data.get(DOMAIN)
    if not data:
        connection.send_error(msg["id"], "not_found", "Update Manager isn't set up")
        return

    identity = _resolve_identity_for_version(hass, data, msg["entity_id"], msg["version"])
    if identity is None:
        connection.send_error(msg["id"], "not_identifiable", "This update can't be identified for voting yet")
        return

    access_token = await data["github_auth_manager"].async_get_valid_access_token()
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
    await data["my_votes_manager"].async_remember(identity.votes_path, msg["verdict"])
    connection.send_result(msg["id"], {"updated": is_vote_update})


def async_setup_websocket_api(hass: HomeAssistant) -> None:
    """Registers the commands once. Safe to call again on entry reload
    (e.g. after saving settings) -- HA raises on a duplicate registration,
    so this is guarded rather than relying on callers."""
    if hass.data.get(_WS_REGISTERED):
        return
    hass.data[_WS_REGISTERED] = True
    websocket_api.async_register_command(hass, _handle_updates)
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
