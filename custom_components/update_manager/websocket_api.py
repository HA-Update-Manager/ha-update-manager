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
    DOMAIN,
    PROFILE_PRESETS,
)
from .coordinator import excluded_entities_from_options, hard_excluded_entity_ids, rules_from_options
from .install_manager import auto_install_rules_from_options

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
    connection.send_result(msg["id"], {"updates": updates})


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
    hass.async_create_task(hass.services.async_call("update", "install", service_data, blocking=True))
    if data:
        # Awaited, not left to the state_changed event clear_skipped above
        # already schedules on its own -- that's a background task HA
        # fires and forgets, not guaranteed to have run yet by the time
        # this handler returns and the panel's own post-call _loadAll()
        # re-fetches (same race already fixed once this session for
        # save_settings/staging_skip.py's own skip/unskip calls).
        await data["coordinator"].async_refresh_one(entity_id)
    connection.send_result(msg["id"])


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
